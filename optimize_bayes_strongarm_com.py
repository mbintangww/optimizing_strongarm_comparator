import csv, json, os, sys, time
import optuna

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_core_strongarm_com import PARAM_CONFIG, RESULTS_DIR, evaluate, apply_constraints

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as _f:
    BAYES_CFG = json.load(_f)["bayes"]
RESULTS_U  = RESULTS_DIR


class _Tee:
    def __init__(self, path):
        self._file = open(path, "w"); self._stdout = sys.stdout; sys.stdout = self
    def write(self, data): self._stdout.write(data); self._file.write(data)
    def flush(self): self._stdout.flush(); self._file.flush()
    def close(self): sys.stdout = self._stdout; self._file.close()


optuna.logging.set_verbosity(optuna.logging.WARNING)


def run_bayes():
    param_names = list(PARAM_CONFIG.keys())
    work_dir    = os.path.join(RESULTS_U, "bayes_strongarm_com_worker")
    os.makedirs(work_dir, exist_ok=True)

    print("=" * 60)
    print("  Bayesian Optimization (Optuna TPE) - strongarm_com.sch (3-stack)")
    print(f"  Parameters : {param_names}")
    print(f"  n_trials={BAYES_CFG['n_trials']}  seed={BAYES_CFG['seed']}")
    print("=" * 60)

    best_so_far = [1e9]

    def objective(trial):
        params = {
            name: trial.suggest_float(name, PARAM_CONFIG[name]["min"], PARAM_CONFIG[name]["max"])
            for name in param_names
        }
        result = evaluate(params, work_dir)
        fom    = apply_constraints(result)
        if result["valid"]:
            trial.set_user_attr("t_regen_ps", result["t_regen_ps"])
            trial.set_user_attr("power_uW",   result["power_uW"])
            trial.set_user_attr("fom_raw",    result["fom"])
        return fom

    def print_progress(study, trial):
        n     = trial.number + 1
        fom   = trial.value
        valid = [t for t in study.trials if t.value is not None and t.value < 1e8]
        best  = min(t.value for t in valid) if valid else float("inf")
        best_so_far[0] = best

        t_ps  = trial.user_attrs.get("t_regen_ps", "-")
        pwr   = trial.user_attrs.get("power_uW",   "-")
        t_str = f"{t_ps:.2f}ps" if isinstance(t_ps, float) else "-"
        p_str = f"{pwr:.1f}µW"  if isinstance(pwr, float) else "-"
        b_str = f"{best:,.1f}"  if best < 1e8 else "none"
        ok    = "OK" if fom < 1e8 else "X "
        print(f"  [{n:3d}/{BAYES_CFG['n_trials']}] {ok}  "
              f"t={t_str:10s}  P={p_str:10s}  "
              f"FoM={fom if fom < 1e8 else 'penalty':>10}  best={b_str}")

    sampler = optuna.samplers.TPESampler(seed=BAYES_CFG["seed"])
    study   = optuna.create_study(direction="minimize", sampler=sampler,
                                  study_name="strongarm_com_3stack_bayes")

    t0 = time.time()
    study.optimize(objective, n_trials=BAYES_CFG["n_trials"], callbacks=[print_progress])
    elapsed = time.time() - t0

    history = []
    for t in study.trials:
        entry = {**t.params,
                 "fom_final":   t.value,
                 "t_regen_ps":  t.user_attrs.get("t_regen_ps"),
                 "power_uW":    t.user_attrs.get("power_uW"),
                 "fom_raw":     t.user_attrs.get("fom_raw"),
                 "valid":       t.value is not None and t.value < 1e8,
                 "trial":       t.number}
        history.append(entry)

    csv_path  = os.path.join(RESULTS_U, "bayes_strongarm_com_history.csv")
    fieldnames = ["trial"] + param_names + ["t_regen_ps", "power_uW", "fom_raw", "fom_final", "valid"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader(); writer.writerows(history)

    valid  = [t for t in study.trials if t.value is not None and t.value < 1e8]
    best_t = study.best_trial if valid else None

    summary = {
        "method":    "Bayesian (Optuna TPE)",
        "topology":  "3-stack StrongARM (strongarm_com.sch)",
        "n_evals":   len(history),
        "n_valid":   len(valid),
        "elapsed_s": round(elapsed, 2),
        "best_fom":  round(best_t.value, 2) if best_t else None,
        "best_params": {k: round(best_t.params[k], 4) for k in param_names} if best_t else None,
        "best_t_regen_ps": round(best_t.user_attrs.get("t_regen_ps", 0), 2) if best_t else None,
        "best_power_uW":   round(best_t.user_attrs.get("power_uW", 0), 1) if best_t else None,
    }
    summary_path = os.path.join(RESULTS_U, "bayes_strongarm_com_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print(f"  BAYESIAN COMPLETE - {elapsed/60:.1f} min")
    if best_t:
        print(f"\n  OPTIMAL SIZING:")
        for k in param_names:
            print(f"    {k} = {best_t.params[k]:.4f} µm")
        t_ps = best_t.user_attrs.get("t_regen_ps", 0)
        pwr  = best_t.user_attrs.get("power_uW", 0)
        print(f"\n  t_regen = {t_ps:.2f} ps")
        print(f"  Power   = {pwr:.1f} µW")
        print(f"  FoM     = {best_t.value:,.1f} ps·µW")
    print("=" * 60)
    print(f"\nCSV    : {csv_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    os.makedirs(RESULTS_U, exist_ok=True)
    tee = _Tee(os.path.join(RESULTS_U, "bayes_strongarm_com_log.txt"))
    try:
        run_bayes()
    finally:
        tee.close()
