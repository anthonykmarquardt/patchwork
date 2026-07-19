#!/usr/bin/env python3
"""Spec 0001 empirical-closure experiments (n=6 battery — directional).

Exp1 embedder/V2 (bge-small locality + LOO tier prediction)
Exp2 per-class verifiers vs the real captured T0/T1 outputs (fixtures/)
Exp3 lambda sweep (utility = quality - lambda*cost), per class

HISTORICAL (Exp 1–3 closed 2026-07-16; results in journal.md/decisions.md).
Predates the mlx embedder port — torch/transformers left this project's env
on 2026-07-18, so to re-run:  uv run --with torch --with 'transformers<6' \
    python closure.py
bge-small-en-v1.5 must be in the HF cache (it is: BAAI/bge-small-en-v1.5).

Caveat: n=6. Exp2 (verifiers vs real failure outputs) closes cleanly. Exp1/Exp3
are DIRECTIONAL — n=6 is the cold-start regime (failure mode P2). See results.md.
"""
import os, re
os.environ["HF_HUB_OFFLINE"] = "1"
import numpy as np

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TIERS = ["T0", "T1", "T2"]

# ---- battery: prompts, subjective quality[tier] (rater=assistant, n=1), costs ----
PROMPTS = {
 "R1": ("reasoning", "Three people check into a hotel room... where did the missing dollar go? Explain precisely what is wrong with this reasoning."),
 "R2": ("reasoning", "A store sells apples at 3 for $1 and oranges at 2 for $1. I buy 24 pieces of fruit total and spend exactly $9. How many apples and oranges?"),
 "A1": ("agentic",   "You are an ops agent with tools run_shell/read_file/http_get/send_slack. Intermittent 502s behind nginx. Give the ordered tool calls to diagnose."),
 "A2": ("agentic",   "A Python batch script suddenly gets OOM-killed at 3am nightly, only in production. Give an ordered diagnostic checklist cheapest-first."),
 "E1": ("emotional", "My dad passed away three weeks ago. We hadn't spoken in two years after a bad fight. I keep swinging between grief and anger. I just needed to say it to someone."),
 "E2": ("emotional", "My best friend got the promotion I was passed over for and wants to celebrate tonight. I'm happy for her and I kind of hate her and I hate that I feel that way. What do I do?"),
}
QUALITY = {  # [T0,T1,T2] in [0,1], from this session's assessments (subjective, n=1)
 "R1": [0.10, 0.85, 1.00], "R2": [1.00, 1.00, 1.00],
 "A1": [0.20, 0.85, 1.00], "A2": [0.35, 0.60, 1.00],
 "E1": [0.35, 0.80, 1.00], "E2": [0.30, 0.75, 0.95],
}
SAT = 0.70                                  # "satisfies" threshold
COST = np.array([5.4, 14.8, 53.0]); COST = COST / COST.max()   # norm latency for ~400 tok
def smallest_sat(q):
    for i,v in enumerate(q):
        if v >= SAT: return i
    return 2
LABEL = {k: smallest_sat(v) for k,v in QUALITY.items()}
IDS = list(PROMPTS)

def banner(s): print("\n" + "="*72 + f"\n{s}\n" + "="*72)

# ============================ EXP 1 — embedder / V2 ============================
def exp1():
    banner("EXP 1 — embedder (bge-small-en-v1.5) : locality + LOO tier prediction")
    from transformers import AutoTokenizer, AutoModel
    import torch
    tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    mdl = AutoModel.from_pretrained("BAAI/bge-small-en-v1.5").eval()
    texts = [PROMPTS[i][1] for i in IDS]
    with torch.no_grad():
        enc = tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
        emb = mdl(**enc).last_hidden_state[:, 0]            # CLS pooling (bge recipe)
        emb = torch.nn.functional.normalize(emb, dim=1).numpy()
    S = emb @ emb.T
    cls = [PROMPTS[i][0] for i in IDS]
    win, cross = [], []
    for a in range(6):
        for b in range(a+1,6):
            (win if cls[a]==cls[b] else cross).append(S[a,b])
    print(f"  within-class cos sim: mean {np.mean(win):.3f}  |  cross-class: mean {np.mean(cross):.3f}"
          f"  -> class-locality {'HOLDS' if np.mean(win)>np.mean(cross) else 'weak'} (gap {np.mean(win)-np.mean(cross):+.3f})")
    print("  nearest neighbour of each prompt:")
    for a in range(6):
        nn = [j for j in np.argsort(-S[a]) if j!=a][0]
        print(f"    {IDS[a]}({cls[a]},lbl {TIERS[LABEL[IDS[a]]]}) -> {IDS[nn]}"
              f"({cls[nn]},lbl {TIERS[LABEL[IDS[nn]]]})  sim {S[a,nn]:.3f}")
    correct = 0
    for a in range(6):
        pred = LABEL[IDS[[j for j in np.argsort(-S[a]) if j!=a][0]]]
        correct += pred == LABEL[IDS[a]]
    base = max(np.bincount([LABEL[i] for i in IDS])) / 6
    print(f"  LOO k=1 tier accuracy: {correct}/6 = {correct/6:.2f}  (majority baseline {base:.2f})"
          f"  -> misses are same-class/different-tier = P1")

# ============================ EXP 2 — verifiers ================================
def load_answers(path):
    parts = re.split(r"(?m)^###\s+\S+\s+\|\s+([A-Z]\d)-", open(path).read())
    it = iter(parts[1:]); out = {}
    for pid, body in zip(it, it):
        if "--- ANSWER ---" in body:
            out[pid] = body.split("--- ANSWER ---")[-1].strip()
    return out

TOOLS = ["run_shell","read_file","http_get","send_slack"]
def v_agentic(t):
    reasons=[]
    for m in re.finditer(r"(run_shell|read_file|http_get|send_slack)\s*\((.*?)\)", t):
        if any(f"{tool}(" in m.group(2) for tool in TOOLS):
            reasons.append(f"nested tool in {m.group(1)}(...)")   # THE signal
    heads = re.findall(r"^#{2,4}\s*\**\s*\d+\.", t, flags=re.M)   # sprawl heuristic (noisy)
    return {"nested": [r for r in reasons], "steps": len(heads)}

def v_reasoning(pid, t):
    tl = t.lower()
    if pid == "R2":
        good = "18" in t and any(k in tl for k in ["6 orange","oranges: 6","oranges = 6","o = 6","**6**"])
        return (not good, [] if good else ["R2 answer not 18/6"])
    if pid == "R1":
        wrong = any(k in tl for k in ["went to the clerk","= $29","= $32","= $35","$3 less"])
        right = any(k in tl for k in ["no missing dollar","not missing at all","already","false total","illusion"])
        return (wrong and not right, ["asserts a real missing dollar"] if (wrong and not right) else [])
    return (False, [])

def v_emotional(t):
    sections = len(re.findall(r"^#{2,4}\s*\**\s*\d+\.", t, flags=re.M)) + \
               len(re.findall(r"^\s*\d+\.\s+\*\*", t, flags=re.M))
    return (sections >= 3, {"sections":sections, "q_marks":t.count("?")})

def exp2():
    banner("EXP 2 — per-class verifiers vs real captured outputs (fixtures/)")
    ans = {"T0": {**load_answers(f"{FIX}/bonsai-1.7b-ternary.reasoning-agentic.txt"),
                  **load_answers(f"{FIX}/bonsai-1.7b-ternary.emotional.txt")},
           "T1": {**load_answers(f"{FIX}/bonsai-8b-ternary.reasoning-agentic.txt"),
                  **load_answers(f"{FIX}/bonsai-8b-ternary.emotional.txt")}}
    print("  AGENTIC (nested-tool check = the signal; step-count = noisy):")
    for tier in ("T0","T1"):
        r = v_agentic(ans[tier].get("A1",""))
        print(f"    {tier}/A1: nested={len(r['nested'])}  steps={r['steps']}  "
              f"-> {'FLAG(nested)' if r['nested'] else 'pass-on-nesting'}")
    print("  REASONING:")
    for pid in ("R1","R2"):
        for tier in ("T0","T1"):
            f,_ = v_reasoning(pid, ans[tier].get(pid,""))
            print(f"    {tier}/{pid}: {'FLAG' if f else 'pass'}")
    print("  EMOTIONAL (listicle heuristic — note misses):")
    for pid in ("E1","E2"):
        for tier in ("T0","T1"):
            f,meta = v_emotional(ans[tier].get(pid,""))
            tag = "  <-MISS (bad but prose)" if (pid=="E1" and tier=="T0" and not f) else \
                  ("  <-over-flag (usable listicle)" if (pid=="E2" and tier=="T1" and f) else "")
            print(f"    {tier}/{pid}: {'FLAG' if f else 'pass'}  {meta}{tag}")

# ============================ EXP 3 — lambda sweep ============================
def exp3():
    banner("EXP 3 — lambda sweep (utility = quality - lambda*cost)")
    for lam in [0.0,0.2,0.3,0.4,0.5,0.7,1.0]:
        picks=[int(np.argmax(np.array(QUALITY[i])-lam*COST)) for i in IDS]
        mq=np.mean([QUALITY[IDS[k]][picks[k]] for k in range(6)])
        mc=np.mean([COST[picks[k]] for k in range(6)])
        print(f"   lam={lam:.2f} | "+" ".join(f"{i}:{TIERS[p]}" for i,p in zip(IDS,picks))
              +f" | Q {mq:.2f} cost {mc:.2f} %<=T1 {np.mean([p<=1 for p in picks])*100:3.0f}")
    print("  per-class ideal-lambda (reproduces smallest-satisfying label):")
    lams=np.round(np.arange(0,2.01,0.05),3)
    for cls in ("reasoning","agentic","emotional"):
        ids=[i for i in IDS if PROMPTS[i][0]==cls]
        ok=[l for l in lams if all(int(np.argmax(np.array(QUALITY[i])-l*COST))==LABEL[i] for i in ids)]
        print(f"    {cls:9s} {[TIERS[LABEL[i]] for i in ids]}  "
              +(f"[{min(ok):.2f},{max(ok):.2f}]" if ok else "(none)"))

if __name__ == "__main__":
    print("battery n=6  labels: "+", ".join(f"{i}->{TIERS[LABEL[i]]}" for i in IDS))
    exp1(); exp2(); exp3()
