"""
M1: Data and parameter setup for EVCS planning on IEEE 33-bus network.

- Defines sets and basic parameters.
- Generates random scenario data (A=10, B=10) into CSV files under ./data/.
- You can later replace random numbers and CSVs with real data.
"""

import csv
import os
from dataclasses import dataclass, asdict
from typing import List, Tuple

import numpy as np


# -------------------------
# Global settings (you can change later)
# -------------------------

N_BUS = 33  # |N|
R_REGIONS = 3  # |R|
T_NOR = 24  # |Tnor|
T_S = 4  # |Ts|
A_SCEN = 10  # A
B_SCEN = 10  # B

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# -------------------------
# Sets and basic structures
# -------------------------

@dataclass
class NetworkSets:
    buses: List[int]  # N
    lines: List[Tuple[int, int]]  # L as (from_bus, to_bus)
    regions: List[int]  # R
    t_nor: List[int]  # Tnor
    t_s: List[int]  # Ts
    scenarios_a: List[int]  # a = 1..A
    scenarios_b: List[int]  # b = 1..B


@dataclass
class EconomicParams:
    """Economic parameters (Section 1.2)."""

    Cfix: float  # fixed station cost
    Ccons_sl: float  # slow charger installation cost
    Ccons_fa: float  # fast charger installation cost
    Ctrans: List[float]  # length |Tnor|
    Cpur: List[float]  # length |Tnor|
    Ccong: float  # congestion penalty
    gamma: float  # discount rate
    theta: int  # payback period (years)
    pi_f: float  # disaster-stage weight
    alpha_min: float = 0.0  # optional lower bound on α (if > 0, forces disaster term up)


@dataclass
class NetworkParams:
    """Network parameters (Section 1.3)."""

    Rline: List[float]  # |L|
    Xline: List[float]  # |L|
    Pmax: List[float]  # |L|
    Qmax: List[float]  # |L|
    Vmin: float
    Vmax: float


@dataclass
class EVParams:
    """EV charging parameters (Section 1.4)."""

    P_EV_rated_sl: float
    P_EV_rated_fa: float
    D: List[List[float]]  # |R| x |N|
    delta_t: float
    Nbar_sl: int
    Nbar_fa: int


@dataclass
class AmbiguityParams:
    """Outage ambiguity parameters (Section 1.7)."""

    K: int  # max simultaneous outages
    p_bar: List[float]  # |L| marginal outage upper bound
    w: List[float]  # |N| load priority weight vector


@dataclass
class ModelParams:
    """Container for all Section 1 parameters."""

    sets: NetworkSets
    econ: EconomicParams
    net: NetworkParams
    ev: EVParams
    ambig: AmbiguityParams


def build_ieee33_sets() -> NetworkSets:
    """IEEE 33-bus topology: use standard 32-line structure."""
    # From Table 7 in the IEEE 33-bus data (Nature / Baran-Wu).
    lines = [
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 8),
        (8, 9),
        (9, 10),
        (10, 11),
        (11, 12),
        (12, 13),
        (13, 14),
        (14, 15),
        (15, 16),
        (16, 17),
        (17, 18),
        (2, 19),
        (19, 20),
        (20, 21),
        (21, 22),
        (3, 23),
        (23, 24),
        (24, 25),
        (6, 26),
        (26, 27),
        (27, 28),
        (28, 29),
        (29, 30),
        (30, 31),
        (31, 32),
        (32, 33),
    ]
    return NetworkSets(
        buses=list(range(1, N_BUS + 1)),
        lines=lines,
        regions=list(range(1, R_REGIONS + 1)),
        t_nor=list(range(1, T_NOR + 1)),
        t_s=list(range(1, T_S + 1)),
        scenarios_a=list(range(1, A_SCEN + 1)),
        scenarios_b=list(range(1, B_SCEN + 1)),
    )


# -------------------------
# IEEE 33 line parameters (R, X, base load P,Q)
# -------------------------

def get_ieee33_line_params():
    """Return (from_bus, to_bus, R_pu, X_pu, P_kW, Q_kvar) for each line."""
    # Data from Nature table (line impedances + loads).
    rows = [
        (1, 2, 0.000574, 0.000293, 100, 60),
        (2, 3, 0.00307, 0.001564, 90, 40),
        (3, 4, 0.002279, 0.001161, 120, 80),
        (4, 5, 0.002373, 0.001209, 60, 30),
        (5, 6, 0.0051, 0.004402, 60, 20),
        (6, 7, 0.001166, 0.003853, 200, 100),
        (7, 8, 0.00443, 0.001464, 200, 100),
        (8, 9, 0.006413, 0.004608, 60, 20),
        (9, 10, 0.006501, 0.004608, 60, 20),
        (10, 11, 0.001224, 0.000405, 45, 30),
        (11, 12, 0.002331, 0.000771, 60, 35),
        (12, 13, 0.009141, 0.007192, 60, 35),
        (13, 14, 0.003372, 0.004439, 120, 80),
        (14, 15, 0.00368, 0.003275, 60, 10),
        (15, 16, 0.004647, 0.003394, 60, 20),
        (16, 17, 0.008026, 0.010716, 60, 20),
        (17, 18, 0.004558, 0.003574, 90, 40),
        (2, 19, 0.001021, 0.000974, 90, 40),
        (19, 20, 0.009366, 0.00844, 90, 40),
        (20, 21, 0.00255, 0.002979, 90, 40),
        (21, 22, 0.004414, 0.005836, 90, 40),
        (3, 23, 0.002809, 0.00192, 90, 50),
        (23, 24, 0.005592, 0.004415, 420, 200),
        (24, 25, 0.005579, 0.004366, 420, 200),
        (6, 26, 0.001264, 0.000644, 60, 25),
        (26, 27, 0.00177, 0.000901, 60, 25),
        (27, 28, 0.006594, 0.005814, 60, 20),
        (28, 29, 0.005007, 0.004362, 120, 70),
        (29, 30, 0.00316, 0.00161, 200, 600),
        (30, 31, 0.006067, 0.005996, 150, 70),
        (31, 32, 0.001933, 0.002253, 210, 100),
        (32, 33, 0.002123, 0.003301, 60, 40),
    ]
    return rows


def build_default_parameters() -> ModelParams:
    """
    Build default values for all Section 1 parameters.
    这里只是示例数值，后期你可以直接改这里或改导出的 JSON。
    """
    sets = build_ieee33_sets()

    # Economic parameters: simple example values (currency units are arbitrary)
    Cfix = 5e5
    Ccons_sl = 5e4
    Ccons_fa = 8e4
    # Ctrans, Cpur: length |Tnor|=24，简单设定为常数或轻微变化
    Ctrans = [1.0 for _ in sets.t_nor]  # currency/km
    Cpur = [0.5 + 0.1 * np.sin(2 * np.pi * (t - 1) / 24.0) for t in sets.t_nor]  # currency/kWh
    Ccong = 10.0
    gamma = 0.06
    theta = 10
    pi_f = 0.1
    econ = EconomicParams(
        Cfix=Cfix,
        Ccons_sl=Ccons_sl,
        Ccons_fa=Ccons_fa,
        Ctrans=Ctrans,
        Cpur=Cpur,
        Ccong=Ccong,
        gamma=gamma,
        theta=theta,
        pi_f=pi_f,
        alpha_min=0.0,
    )

    # Network parameters: use IEEE33 R,X as base; simple Pmax,Qmax, voltage limits
    line_rows = get_ieee33_line_params()
    Rline = [r for (_, _, r, _, _, _) in line_rows]
    Xline = [x for (_, _, _, x, _, _) in line_rows]
    # 设置一个统一的容量上限
    Pmax = [10000.0 for _ in line_rows]  # kW
    Qmax = [10000.0 for _ in line_rows]  # kvar
    Vmin = 0.9
    Vmax = 1.1
    net = NetworkParams(Rline=Rline, Xline=Xline, Pmax=Pmax, Qmax=Qmax, Vmin=Vmin, Vmax=Vmax)

    # EV parameters: 简单示例
    P_EV_rated_sl = 7.0  # kW
    P_EV_rated_fa = 50.0  # kW
    # D: |R| x |N| 距离矩阵，先用 1~10km 的随机数（后期你可以用真实距离替换）
    rng = np.random.default_rng(42)
    D = rng.uniform(1.0, 10.0, size=(R_REGIONS, N_BUS)).round(3).tolist()
    delta_t = 1.0  # hour
    Nbar_sl = 20
    Nbar_fa = 10
    ev = EVParams(
        P_EV_rated_sl=P_EV_rated_sl,
        P_EV_rated_fa=P_EV_rated_fa,
        D=D,
        delta_t=delta_t,
        Nbar_sl=Nbar_sl,
        Nbar_fa=Nbar_fa,
    )

    # Ambiguity parameters
    K = 4
    # 每条线的边际故障上界 p_bar_mn：在 [0.05, 0.2] 区间内随机生成，且彼此不完全相同
    rng_ambig = np.random.default_rng(54321)
    p_bar = [float(rng_ambig.uniform(0.05, 0.2)) for _ in line_rows]
    # Load priority weights w_n：在 {1, 50, 200} 中为每个节点随机分配一个权重
    rng_w = np.random.default_rng(12345)
    w_choices = [1.0, 50.0, 200.0]
    w = [float(rng_w.choice(w_choices)) for _ in sets.buses]
    ambig = AmbiguityParams(K=K, p_bar=p_bar, w=w)

    return ModelParams(sets=sets, econ=econ, net=net, ev=ev, ambig=ambig)


def load_parameters(base_dir: str = None) -> ModelParams:
    """
    Load parameters.json and reconstruct ModelParams.
    供 M2/M3 等模块直接使用，避免重复写解析逻辑。
    """
    import json

    if base_dir is None:
        base_dir = os.path.dirname(__file__)
    param_path = os.path.join(base_dir, "data", "parameters.json")
    with open(param_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    sets_raw = raw["sets"]
    econ_raw = raw["econ"]
    net_raw = raw["net"]
    ev_raw = raw["ev"]
    ambig_raw = raw["ambig"]

    sets = NetworkSets(
        buses=sets_raw["buses"],
        lines=[tuple(x) for x in sets_raw["lines"]],
        regions=sets_raw["regions"],
        t_nor=sets_raw["t_nor"],
        t_s=sets_raw["t_s"],
        scenarios_a=sets_raw["scenarios_a"],
        scenarios_b=sets_raw["scenarios_b"],
    )
    econ = EconomicParams(
        Cfix=econ_raw["Cfix"],
        Ccons_sl=econ_raw["Ccons_sl"],
        Ccons_fa=econ_raw["Ccons_fa"],
        Ctrans=econ_raw["Ctrans"],
        Cpur=econ_raw["Cpur"],
        Ccong=econ_raw["Ccong"],
        gamma=econ_raw["gamma"],
        theta=econ_raw["theta"],
        pi_f=econ_raw["pi_f"],
        alpha_min=econ_raw.get("alpha_min", 0.0),
    )
    net = NetworkParams(
        Rline=net_raw["Rline"],
        Xline=net_raw["Xline"],
        Pmax=net_raw["Pmax"],
        Qmax=net_raw["Qmax"],
        Vmin=net_raw["Vmin"],
        Vmax=net_raw["Vmax"],
    )
    ev = EVParams(
        P_EV_rated_sl=ev_raw["P_EV_rated_sl"],
        P_EV_rated_fa=ev_raw["P_EV_rated_fa"],
        D=ev_raw["D"],
        delta_t=ev_raw["delta_t"],
        Nbar_sl=ev_raw["Nbar_sl"],
        Nbar_fa=ev_raw["Nbar_fa"],
    )
    ambig = AmbiguityParams(
        K=ambig_raw["K"],
        p_bar=ambig_raw["p_bar"],
        w=ambig_raw["w"],
    )

    return ModelParams(sets=sets, econ=econ, net=net, ev=ev, ambig=ambig)


def write_base_network_csv():
    os.makedirs(DATA_DIR, exist_ok=True)

    # nodes.csv
    with open(os.path.join(DATA_DIR, "nodes.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["bus_id"])
        for n in range(1, N_BUS + 1):
            writer.writerow([n])

    # lines.csv
    with open(os.path.join(DATA_DIR, "lines.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["from_bus", "to_bus", "R_pu", "X_pu", "P_base_kW", "Q_base_kvar"])
        for row in get_ieee33_line_params():
            writer.writerow(row)

    # EV regions: simple mapping (later you can change)
    with open(os.path.join(DATA_DIR, "ev_regions.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["region_id"])
        for r in range(1, R_REGIONS + 1):
            writer.writerow([r])


# -------------------------
# Random scenario data generation
# -------------------------

def random_daily_profile(T: int, base: float, peak_factor: float = 1.5) -> np.ndarray:
    """
    Simple smooth daily profile: base * (0.5 + something between 0 and peak_factor).
    """
    hours = np.arange(T)
    # Peak around 18:00 (hour 18) using cosine
    peak_center = 18.0
    width = 6.0
    profile = 0.6 + 0.9 * np.exp(-((hours - peak_center) ** 2) / (2 * width**2))
    # Normalize to mean 1
    profile = profile / profile.mean()
    return base * profile


def generate_normal_scenarios(net: NetworkSets, seed: int = 123) -> None:
    """
    Generate:
    - normal_load_scenarios.csv: a, t, n, P_kW, Q_kvar
    - normal_ev_demand_slow.csv: a, t, r, DEV_ch_sl_kW
    - normal_ev_demand_fast.csv: a, t, r, DEV_ch_fa_kW
    """
    rng = np.random.default_rng(seed)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Base load from line data (approximate bus load by downstream line load)
    base_lines = get_ieee33_line_params()
    # Map from bus to base P,Q
    base_P = {to_bus: P for (_, to_bus, _, _, P, _) in base_lines}
    base_Q = {to_bus: Q for (_, to_bus, _, _, _, Q) in base_lines}

    # normal_load_scenarios.csv（负荷整体缩放为约 0.5 倍）
    load_scale = 0.5
    with open(os.path.join(DATA_DIR, "normal_load_scenarios.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scenario_a", "t", "bus", "P_kW", "Q_kvar"])
        for a in net.scenarios_a:
            # small scenario-specific multiplier
            scen_factor = rng.normal(loc=1.0, scale=0.05)
            for n in net.buses:
                P0 = base_P.get(n, 0.0)
                Q0 = base_Q.get(n, 0.0)
                if P0 == 0 and Q0 == 0:
                    continue
                # Daily profiles: base * load_scale * scen_factor
                P_profile = random_daily_profile(T_NOR, load_scale * P0 * scen_factor)
                Q_profile = random_daily_profile(T_NOR, load_scale * Q0 * scen_factor)
                for t_idx, (p_t, q_t) in enumerate(zip(P_profile, Q_profile), start=1):
                    writer.writerow(
                        [a, t_idx, n, round(float(p_t), 3), round(float(q_t), 3)]
                    )

    # EV demand profiles per region (slow/fast)
    with open(os.path.join(DATA_DIR, "normal_ev_demand_slow.csv"), "w", newline="") as f_sl, open(
        os.path.join(DATA_DIR, "normal_ev_demand_fast.csv"), "w", newline=""
    ) as f_fa:
        w_sl = csv.writer(f_sl)
        w_fa = csv.writer(f_fa)
        w_sl.writerow(["scenario_a", "t", "region", "DEV_ch_sl_kW"])
        w_fa.writerow(["scenario_a", "t", "region", "DEV_ch_fa_kW"])

        # EV 场景缩放（当前为原先的 0.5 倍，与负荷一致）
        ev_scale = 5.0  # 10.0 * 0.5
        for a in net.scenarios_a:
            for r in net.regions:
                base_slow = rng.uniform(50, 150)
                base_fast = rng.uniform(30, 100)
                prof_sl = random_daily_profile(T_NOR, base_slow)
                prof_fa = random_daily_profile(T_NOR, base_fast)
                for t_idx in net.t_nor:
                    w_sl.writerow([a, t_idx, r, round(ev_scale * float(prof_sl[t_idx - 1]), 3)])
                    w_fa.writerow([a, t_idx, r, round(ev_scale * float(prof_fa[t_idx - 1]), 3)])


def load_normal_scenario_data(
    scenario_a: int,
    data_dir: str | None = None,
) -> dict:
    """
    Load normal-stage scenario data for a given scenario index a.
    Returns dict with keys: P_Load, Q_Load, DEV_ch_sl, DEV_ch_fa.
    - P_Load[(t,n)], Q_Load[(t,n)]: kW, kvar
    - DEV_ch_sl[(t,r)], DEV_ch_fa[(t,r)]: kW
    """
    if data_dir is None:
        data_dir = DATA_DIR
    P_Load = {}
    Q_Load = {}
    with open(os.path.join(data_dir, "normal_load_scenarios.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_a"]) != scenario_a:
                continue
            t, n = int(row["t"]), int(row["bus"])
            P_Load[(t, n)] = float(row["P_kW"])
            Q_Load[(t, n)] = float(row["Q_kvar"])
    DEV_ch_sl = {}
    DEV_ch_fa = {}
    with open(os.path.join(data_dir, "normal_ev_demand_slow.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_a"]) != scenario_a:
                continue
            t, r = int(row["t"]), int(row["region"])
            DEV_ch_sl[(t, r)] = float(row["DEV_ch_sl_kW"])
    with open(os.path.join(data_dir, "normal_ev_demand_fast.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_a"]) != scenario_a:
                continue
            t, r = int(row["t"]), int(row["region"])
            DEV_ch_fa[(t, r)] = float(row["DEV_ch_fa_kW"])
    return {"P_Load": P_Load, "Q_Load": Q_Load, "DEV_ch_sl": DEV_ch_sl, "DEV_ch_fa": DEV_ch_fa}


def load_disaster_scenario_data(
    scenario_b: int,
    data_dir: str | None = None,
) -> dict:
    """
    Load disaster-stage scenario data for a given scenario index b.
    Returns dict with keys: P_Load, DEV_dis_sl, DEV_dis_fa.
    - P_Load[(ts,n)]: kW
    - DEV_dis_sl[(ts,r)], DEV_dis_fa[(ts,r)]: kW
    """
    if data_dir is None:
        data_dir = DATA_DIR
    P_Load = {}
    with open(os.path.join(data_dir, "disaster_load_scenarios.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_b"]) != scenario_b:
                continue
            ts, n = int(row["ts"]), int(row["bus"])
            P_Load[(ts, n)] = float(row["P_kW"])
    DEV_dis_sl = {}
    DEV_dis_fa = {}
    with open(os.path.join(data_dir, "disaster_ev_discharge_slow.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_b"]) != scenario_b:
                continue
            ts, r = int(row["ts"]), int(row["region"])
            DEV_dis_sl[(ts, r)] = float(row["DEV_dis_sl_kW"])
    with open(os.path.join(data_dir, "disaster_ev_discharge_fast.csv"), "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["scenario_b"]) != scenario_b:
                continue
            ts, r = int(row["ts"]), int(row["region"])
            DEV_dis_fa[(ts, r)] = float(row["DEV_dis_fa_kW"])
    return {"P_Load": P_Load, "DEV_dis_sl": DEV_dis_sl, "DEV_dis_fa": DEV_dis_fa}


def generate_disaster_scenarios(net: NetworkSets) -> None:
    """
    Generate disaster-stage data by directly reusing normal-stage
    10:00–14:00 (hours 10–13) profiles:

    - disaster_load_scenarios.csv: P_load^b_ts,n := P_load^a=t(10..13),n
    - disaster_ev_discharge_slow.csv: DEV_dis_sl^b_ts,r := DEV_ch_sl^a,t(10..13),r
    - disaster_ev_discharge_fast.csv: DEV_dis_fa^b_ts,r := DEV_ch_fa^a,t(10..13),r

    Mapping: for simplicity use a = b (since A=B=10).
    Ts indices 1..4 correspond to normal hours t = 10,11,12,13.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load normal load scenarios into dict: (a, t, n) -> P_kW
    normal_load_path = os.path.join(DATA_DIR, "normal_load_scenarios.csv")
    load_dict = {}
    with open(normal_load_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = int(row["scenario_a"])
            t = int(row["t"])
            n = int(row["bus"])
            p = float(row["P_kW"])
            load_dict[(a, t, n)] = p

    # Load normal EV demand (slow/fast): (a, t, r) -> kW
    normal_sl_path = os.path.join(DATA_DIR, "normal_ev_demand_slow.csv")
    normal_fa_path = os.path.join(DATA_DIR, "normal_ev_demand_fast.csv")
    ev_sl_dict = {}
    ev_fa_dict = {}
    with open(normal_sl_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = int(row["scenario_a"])
            t = int(row["t"])
            r = int(row["region"])
            val = float(row["DEV_ch_sl_kW"])
            ev_sl_dict[(a, t, r)] = val
    with open(normal_fa_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a = int(row["scenario_a"])
            t = int(row["t"])
            r = int(row["region"])
            val = float(row["DEV_ch_fa_kW"])
            ev_fa_dict[(a, t, r)] = val

    # Mapping Ts=1..4 -> normal hours t=10..13
    ts_to_t = {1: 10, 2: 11, 3: 12, 4: 13}

    # Disaster load: copy from normal load
    with open(os.path.join(DATA_DIR, "disaster_load_scenarios.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scenario_b", "ts", "bus", "P_kW"])
        for b in net.scenarios_b:
            a = b if b in net.scenarios_a else net.scenarios_a[0]
            for ts in net.t_s:
                t = ts_to_t[ts]
                for n in net.buses:
                    p = load_dict.get((a, t, n), 0.0)
                    if p == 0.0:
                        continue
                    writer.writerow([b, ts, n, round(float(p), 3)])

    # Disaster EV discharge (slow/fast): copy from normal EV demand
    with open(
        os.path.join(DATA_DIR, "disaster_ev_discharge_slow.csv"), "w", newline=""
    ) as f_sl, open(
        os.path.join(DATA_DIR, "disaster_ev_discharge_fast.csv"), "w", newline=""
    ) as f_fa:
        w_sl = csv.writer(f_sl)
        w_fa = csv.writer(f_fa)
        w_sl.writerow(["scenario_b", "ts", "region", "DEV_dis_sl_kW"])
        w_fa.writerow(["scenario_b", "ts", "region", "DEV_dis_fa_kW"])

        for b in net.scenarios_b:
            a = b if b in net.scenarios_a else net.scenarios_a[0]
            for ts in net.t_s:
                t = ts_to_t[ts]
                for r in net.regions:
                    val_sl = ev_sl_dict.get((a, t, r), 0.0)
                    val_fa = ev_fa_dict.get((a, t, r), 0.0)
                    w_sl.writerow([b, ts, r, round(float(val_sl), 3)])
                    w_fa.writerow([b, ts, r, round(float(val_fa), 3)])


def generate_all():
    """
    Entry point to generate all data for M1.

    - 写出集合/拓扑/场景数据到 CSV；
    - 写出一个 parameters.json，包含 Section 1 里所有经济/网络/EV/模糊参数的示例值。
    """
    params = build_default_parameters()
    net = params.sets

    write_base_network_csv()
    generate_normal_scenarios(net)
    generate_disaster_scenarios(net)

    # 写出经济/网络/EV/模糊参数到 JSON，方便后期直接修改
    os.makedirs(DATA_DIR, exist_ok=True)
    import json

    with open(os.path.join(DATA_DIR, "parameters.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(params), f, indent=2)

    print(f"Data generated under: {DATA_DIR}")


if __name__ == "__main__":
    generate_all()

