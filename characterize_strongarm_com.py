#!/usr/bin/env python3
"""characterize_strongarm_com.py - Characterize 3-stack StrongARM (strongarm_com.sch)."""
import json, os, re, subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR   = os.path.join(SCRIPT_DIR, "results", "char_strongarm_com")
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "strongarm_com_run.spice")

with open(os.path.join(SCRIPT_DIR, "config.json")) as _f:
    _cfg = json.load(_f)

VDD            = _cfg["circuit"]["VDD"]
BASELINE_VCM   = _cfg["baseline"]["vcm"]
BASELINE_VDIFF = _cfg["baseline"]["vdiff"]
VDIFF_SWEEP    = _cfg["sweep"]["vdiff"]
VCM_SWEEP      = _cfg["sweep"]["vcm"]

TX_PARAM_MAP = {
    "XM1": "WN_IN",  "XM2": "WN_IN",
    "XM3": "WN_LAT", "XM4": "WN_LAT",
    "XM5": "WP_LAT", "XM6": "WP_LAT",
    "XM7": "WN_TAIL",
    "XS1": "WP_RST", "XS2": "WP_RST",
    "XS3": "WP_RST", "XS4": "WP_RST",
}


def build_netlist(params=None, vcm=None, vdiff=None, waveform_path=None):
    if vcm is None:
        vcm = BASELINE_VCM
    if vdiff is None:
        vdiff = BASELINE_VDIFF

    with open(TEMPLATE_PATH) as f:
        content = f.read()

    vinp = vcm + vdiff / 2
    vinn = vcm - vdiff / 2
    content = re.sub(r"VVINN net14 GND [\d.]+", f"VVINN net14 GND {vinn:.6f}", content)
    content = re.sub(r"VVINP net15 GND [\d.]+", f"VVINP net15 GND {vinp:.6f}", content)

    if params:
        for tx, pname in TX_PARAM_MAP.items():
            if pname in params:
                W = params[pname]
                pat = rf"^({re.escape(tx)} \S+ \S+ \S+ \S+ \S+ L=0\.15 W=)[\d.]+"
                rep = rf"\g<1>{W:.4f}"
                content = re.sub(pat, rep, content, flags=re.MULTILINE)

    if waveform_path:
        lines = []
        skip = False
        for line in content.splitlines():
            s = line.strip().lower()
            if s.startswith(".tran") or s.startswith(".measure"):
                skip = True
                continue
            if skip and s.startswith("+"):
                continue
            skip = False
            if s == ".end":
                continue
            lines.append(line)

        control = (
            "\n.control\n"
            "tran 10p 10n\n"
            "meas tran t_regen TRIG v(net2) VAL=0.9 RISE=1 TARG v(net5) VAL=0.9 FALL=1\n"
            "meas tran pwr_avg AVG i(VVDD) FROM=3n TO=9n\n"
            "print t_regen\n"
            "print pwr_avg\n"
            "set wr_singlescale\n"
            "set wr_vecnames\n"
            f"wrdata {waveform_path} v(net2) v(net4) v(net5) v(net9) v(net11)\n"
            ".endc\n"
            ".end\n"
        )
        content = "\n".join(lines) + control

    return content


def run_ngspice(content):
    path = os.path.join(RESULTS_DIR, f"_tmp_{os.getpid()}.spice")
    with open(path, "w") as f:
        f.write(content)
    r = subprocess.run(["ngspice", "-b", path], capture_output=True, text=True, timeout=60)
    os.unlink(path)
    return r.stdout + r.stderr


def parse_measure(output, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-+]?\d+\.?\d*(?:[eE][+-]?\d+)?)",
                  output, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return None if abs(val) > 1e37 else val
    return None


def run_point(params=None, vcm=None, vdiff=None, waveform_path=None):
    content = build_netlist(params, vcm, vdiff, waveform_path)
    out = run_ngspice(content)
    t = parse_measure(out, "t_regen")
    p = parse_measure(out, "pwr_avg")
    t_ps = t * 1e12 if t is not None else None
    p_uW = abs(p) * VDD * 1e6 if p is not None else None
    return t_ps, p_uW


def read_waveform(path):
    data, headers = {}, None
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            try:
                float(parts[0])
                if headers:
                    for h, v in zip(headers, parts):
                        try:
                            data[h].append(float(v))
                        except ValueError:
                            pass
            except ValueError:
                headers = parts
                for h in headers:
                    data[h] = []
    return data


def load_optimal_params():
    summary_path = os.path.join(SCRIPT_DIR, "results", "bayes_strongarm_com_summary.json")
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            data = json.load(f)
        if data.get("best_params"):
            print(f"Using Bayesian optimal sizing (FoM={data['best_fom']:.1f} ps·µW)")
            return data["best_params"]
    print("Bayesian summary not found, cannot proceed without optimal params.")
    raise FileNotFoundError("bayes_strongarm_com_summary.json not found.")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("=== Characterize strongarm_com.sch (3-stack StrongARM + RS Latch) ===\n")

    params = load_optimal_params()

    # --- Test 1: Baseline waveform ---
    print(f"[1/3] Baseline waveform (Vdiff={BASELINE_VDIFF*1000:.0f}mV, Vcm={BASELINE_VCM}V) ...")
    wf_path = os.path.join(RESULTS_DIR, "waveform_baseline.txt")
    t_nom, p_nom = run_point(params=params, waveform_path=wf_path)
    if t_nom:
        print(f"  t_regen = {t_nom:.1f} ps,  Power = {p_nom:.1f} µW")
    else:
        print("  FAILED - check strongarm_com_run.spice")

    if os.path.exists(wf_path):
        data = read_waveform(wf_path)
        keys = list(data.keys())
        if len(keys) >= 2:
            t_ns = np.array(data[keys[0]]) * 1e9
            title = (f"Vdiff={BASELINE_VDIFF*1000:.0f}mV, Vcm={BASELINE_VCM}V, "
                     f"t_regen={t_nom:.1f}ps, P={p_nom:.1f}uW") if t_nom else "Default value waveform"

            # Plot 1: CLK, vx, vy
            fig, ax = plt.subplots(figsize=(10, 4))
            for k, label in [("v(net2)", "CLK"), ("v(net4)", "vx"), ("v(net5)", "vy")]:
                if k in data:
                    ax.plot(t_ns, data[k], label=label)
            ax.axhline(0.9, color="gray", ls="--", lw=0.8, label="0.9V")
            ax.set_title(title)
            ax.set_xlabel("Time (ns)")
            ax.set_ylabel("Voltage (V)")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            png1 = os.path.join(RESULTS_DIR, "waveform_clk_vx_vy.png")
            plt.savefig(png1, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"  -> {png1}")

            # Plot 2: OUTP, OUTN
            fig, ax = plt.subplots(figsize=(10, 4))
            for k, label in [("v(net9)", "OUTP"), ("v(net11)", "OUTN")]:
                if k in data:
                    ax.plot(t_ns, data[k], label=label)
            ax.set_title(title)
            ax.set_xlabel("Time (ns)")
            ax.set_ylabel("Voltage (V)")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            png2 = os.path.join(RESULTS_DIR, "waveform_outp_outn.png")
            plt.savefig(png2, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"  -> {png2}")

    # --- Test 2: Vdiff sweep ---
    print(f"\n[2/3] Vdiff sweep (Vcm={BASELINE_VCM}V) ...")
    res_vd = []
    for vd in VDIFF_SWEEP:
        t, p = run_point(params=params, vcm=BASELINE_VCM, vdiff=vd)
        res_vd.append((vd * 1000, t, p))
        if t:
            print(f"  {vd*1000:5.1f} mV -> {t:.1f} ps")
        else:
            print(f"  {vd*1000:5.1f} mV -> FAILED")

    valid = [(a, b, c) for a, b, c in res_vd if b is not None]
    if valid:
        vd_arr, t_arr, _ = zip(*valid)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(vd_arr, t_arr, "o-", color="steelblue")
        ax.set_xlabel("Vdiff (mV)")
        ax.set_ylabel("t_regen (ps)")
        ax.set_title(f"t_regen vs Vdiff  (Vcm={BASELINE_VCM}V)")
        ax.grid(alpha=0.3)
        png = os.path.join(RESULTS_DIR, "vdiff_sweep.png")
        plt.savefig(png, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  -> {png}")

    # --- Test 3: Vcm sweep ---
    print(f"\n[3/3] Vcm sweep (Vdiff={BASELINE_VDIFF*1000:.0f}mV) ...")
    res_vcm = []
    for vcm in VCM_SWEEP:
        t, p = run_point(params=params, vcm=vcm, vdiff=BASELINE_VDIFF)
        res_vcm.append((vcm, t, p))
        if t:
            print(f"  Vcm={vcm:.3f}V -> {t:.1f} ps")
        else:
            print(f"  Vcm={vcm:.3f}V -> FAILED")

    valid = [(a, b, c) for a, b, c in res_vcm if b is not None]
    if valid:
        vcm_arr, t_arr, _ = zip(*valid)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(vcm_arr, t_arr, "o-", color="green")
        ax.set_xlabel("Vcm (V)")
        ax.set_ylabel("t_regen (ps)")
        ax.set_title(f"t_regen vs Vcm  (Vdiff={BASELINE_VDIFF*1000:.0f}mV)")
        ax.grid(alpha=0.3)
        png = os.path.join(RESULTS_DIR, "vcm_sweep.png")
        plt.savefig(png, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  -> {png}")

    # --- Summary ---
    print("\n=== Results ===")
    print("Sizing used:")
    for k, v in params.items():
        print(f"  {k:10s} = {v} µm")
    if t_nom and p_nom:
        print(f"\nBaseline (Vdiff={BASELINE_VDIFF*1000:.0f}mV, Vcm={BASELINE_VCM}V):")
        print(f"  t_regen = {t_nom:.1f} ps")
        print(f"  Power   = {p_nom:.1f} µW")
        print(f"  FoM     = {t_nom * p_nom:.1f} ps·µW")

    summary = {
        "topology": "3-stack StrongARM + 2-stage RS latch (strongarm_com.sch)",
        "params": params,
        "t_regen_ps": t_nom,
        "power_uW": p_nom,
        "fom": round(t_nom * p_nom, 2) if t_nom and p_nom else None,
    }
    with open(os.path.join(RESULTS_DIR, "char_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nFiles saved to: {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
