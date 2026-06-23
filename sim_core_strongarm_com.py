"""sim_core_strongarm_com.py - simulation core for 3-stack StrongARM (strongarm_com.sch)."""
import json, os, re, subprocess

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR   = os.path.join(SCRIPT_DIR, "results")
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "strongarm_com_run.spice")

with open(os.path.join(SCRIPT_DIR, "config.json")) as _f:
    _cfg = json.load(_f)

VDD          = _cfg["circuit"]["VDD"]
PARAM_CONFIG = _cfg["param_ranges"]
CONSTRAINTS  = _cfg["constraints"]

TX_PARAM_MAP = {
    "XM1": "WN_IN",  "XM2": "WN_IN",
    "XM3": "WN_LAT", "XM4": "WN_LAT",
    "XM5": "WP_LAT", "XM6": "WP_LAT",
    "XM7": "WN_TAIL",
    "XS1": "WP_RST", "XS2": "WP_RST",
    "XS3": "WP_RST", "XS4": "WP_RST",
}


def generate_netlist(params, work_dir):
    with open(TEMPLATE_PATH) as f:
        content = f.read()
    for tx, pname in TX_PARAM_MAP.items():
        if pname in params:
            W   = params[pname]
            pat = rf"^({re.escape(tx)} \S+ \S+ \S+ \S+ \S+ L=0\.15 W=)[\d.]+"
            rep = rf"\g<1>{W:.4f}"
            content = re.sub(pat, rep, content, flags=re.MULTILINE)
    path = os.path.join(work_dir, f"run_{os.getpid()}.spice")
    with open(path, "w") as f:
        f.write(content)
    return path


def run_ngspice(path):
    r = subprocess.run(["ngspice", "-b", path], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def _parse(output, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-+]?\d+\.?\d*(?:[eE][+-]?\d+)?)",
                  output, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return None if abs(val) > 1e37 else val
    return None


def evaluate(params, work_dir=None):
    if work_dir is None:
        work_dir = RESULTS_DIR
    os.makedirs(work_dir, exist_ok=True)

    path   = generate_netlist(params, work_dir)
    output = run_ngspice(path)

    t    = _parse(output, "t_regen")
    p    = _parse(output, "pwr_avg")
    t_ps = t * 1e12 if t is not None else None
    p_uW = abs(p) * VDD * 1e6 if p is not None else None
    fom  = t_ps * p_uW if (t_ps and p_uW and t_ps > 0 and p_uW > 0) else None

    return {"t_regen_ps": t_ps, "power_uW": p_uW, "fom": fom, "valid": fom is not None}


def apply_constraints(result):
    PENALTY = 1e9
    if not result["valid"]:
        return PENALTY
    if result["t_regen_ps"] > CONSTRAINTS["t_regen_max_ps"]:
        return PENALTY
    if result["power_uW"] > CONSTRAINTS["power_max_uW"]:
        return PENALTY
    return result["fom"]
