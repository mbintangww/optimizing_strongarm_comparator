import csv, json, os, sys, time
from scipy.optimize import differential_evolution

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_core_strongarm_com import PARAM_CONFIG, RESULTS_DIR, evaluate, apply_constraints

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as _f:
    DE_CFG = json.load(_f)["de"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_U  = RESULTS_DIR


class _Tee:
    def __init__(self, path):
        self._file = open(path, "w"); self._stdout = sys.stdout; sys.stdout = self
    def write(self, data): self._stdout.write(data); self._file.write(data)
    def flush(self): self._stdout.flush(); self._file.flush()
    def close(self): sys.stdout = self._stdout; self._file.close()


_param_names = None
_workers_dir = None


def _de_objective(x):
    params   = dict(zip(_param_names, x))
    work_dir = os.path.join(_workers_dir, str(os.getpid()))
    os.makedirs(work_dir, exist_ok=True)
    result   = evaluate(params, work_dir)
    return apply_constraints(result)


def run_de():
    global _param_names, _workers_dir

    _param_names = list(PARAM_CONFIG.keys())
    bounds       = [(PARAM_CONFIG[k]["min"], PARAM_CONFIG[k]["max"]) for k in _param_names]

    _workers_dir = os.path.join(RESULTS_U, "de_strongarm_com_workers")
    os.makedirs(_workers_dir, exist_ok=True)

    print("=" * 60)
    print("  Differential Evolution - strongarm_com.sch (3-stack)")
    print(f"  Parameters : {_param_names}")
    print(f"  popsize={DE_CFG['popsize']}  maxiter={DE_CFG['maxiter']}  seed={DE_CFG['seed']}")
    print("=" * 60)

    gen_counter  = [0]
    best_history = []

    def callback(xk, convergence):
        gen_counter[0] += 1
        n      = gen_counter[0] * DE_CFG["popsize"] * len(_param_names)
        params = dict(zip(_param_names, xk))
        result = evaluate(params, _workers_dir)
        fom    = apply_constraints(result)
        best_history.append({
            "gen": gen_counter[0], "n_eval_approx": n,
            "best_fom": fom, "convergence": convergence,
            **params,
            "t_regen_ps": result.get("t_regen_ps"),
            "power_uW":   result.get("power_uW"),
        })
        t_str = f"{result['t_regen_ps']:.1f}ps" if result.get("t_regen_ps") else "-"
        print(f"  Gen {gen_counter[0]:3d} | ~{n} evals | "
              f"best_FoM={fom:,.1f} | t={t_str} | conv={convergence:.4f}")

    t0 = time.time()
    result = differential_evolution(
        _de_objective, bounds,
        popsize=DE_CFG["popsize"], maxiter=DE_CFG["maxiter"],
        workers=DE_CFG["workers"], seed=DE_CFG["seed"],
        tol=DE_CFG["tol"], polish=False, updating="deferred",
        callback=callback,
    )
    elapsed = time.time() - t0

    valid = [e for e in best_history if e["best_fom"] < 1e8]
    best  = min(valid, key=lambda e: e["best_fom"]) if valid else None

    final_params = dict(zip(_param_names, result.x))
    final_result = evaluate(final_params, _workers_dir)
    final_fom    = apply_constraints(final_result)
    if final_fom < (best["best_fom"] if best else 1e9):
        best = {"gen": gen_counter[0], "best_fom": final_fom,
                **final_params,
                "t_regen_ps": final_result.get("t_regen_ps"),
                "power_uW":   final_result.get("power_uW")}

    csv_path = os.path.join(RESULTS_U, "de_strongarm_com_history.csv")
    fieldnames = ["gen", "n_eval_approx", "best_fom", "convergence",
                  "t_regen_ps", "power_uW"] + _param_names
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader(); writer.writerows(best_history)

    summary = {
        "method":    "Differential Evolution",
        "topology":  "3-stack StrongARM (strongarm_com.sch)",
        "n_evals":   gen_counter[0] * DE_CFG["popsize"] * len(_param_names),
        "n_valid":   len(valid),
        "elapsed_s": round(elapsed, 2),
        "best_fom":  round(best["best_fom"], 2) if best else None,
        "best_params": {k: round(best[k], 4) for k in _param_names} if best else None,
        "best_t_regen_ps": round(best["t_regen_ps"], 2) if best and best.get("t_regen_ps") else None,
        "best_power_uW":   round(best["power_uW"], 1) if best and best.get("power_uW") else None,
        "scipy_success":   bool(result.success),
        "scipy_message":   result.message,
    }
    summary_path = os.path.join(RESULTS_U, "de_strongarm_com_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print(f"  DE COMPLETE - {elapsed/60:.1f} min")
    if best:
        print(f"\n  OPTIMAL SIZING:")
        for k in _param_names:
            print(f"    {k} = {best[k]:.4f} µm")
        print(f"\n  t_regen = {best['t_regen_ps']:.2f} ps")
        print(f"  Power   = {best['power_uW']:.1f} µW")
        print(f"  FoM     = {best['best_fom']:,.1f} ps·µW")
    print("=" * 60)
    print(f"\nCSV    : {csv_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    os.makedirs(RESULTS_U, exist_ok=True)
    tee = _Tee(os.path.join(RESULTS_U, "de_strongarm_com_log.txt"))
    try:
        run_de()
    finally:
        tee.close()
