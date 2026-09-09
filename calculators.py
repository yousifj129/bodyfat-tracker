"""
calculators.py
================
A collection of tape-measure / scale-only body fat percentage estimators,
plus derived physique-analysis metrics (waist-to-height ratio, waist-to-hip
ratio, shoulder-to-waist "V-taper", arm-to-wrist ratio, FFMI) and a
transparent composite Body Score.

Every %BF formula in this file only requires: height, weight, age, sex, and
circumference ("tape measure") readings -- NO skinfold calipers, NO DEXA,
NO BIA scale required.

All internal math for the %BF formulas is done in US customary units
(inches, pounds) because that is the unit system nearly all of the
published formulas were derived in. A small unit-conversion registry below
lets the GUI accept ANY mix of imperial/metric units per field and convert
cleanly to/from the canonical inches/lb used internally.

Sources (see README.md for full citations):
  - US Navy / DoD circumference method      (Hodgdon & Beckett, 1984)
  - YMCA method
  - Covert Bailey method                    ("The Ultimate Fit or Fat", 1999)
  - Katch-McArdle circumference method      (Katch & McArdle, 1983)
  - BMI-based method                        (Deurenberg, Weststrate & Seidell, 1991)
  - Multi-Site Regression method (13-var)   -- fit by us against the public
    Penrose/Nelson/Fisher (1985) 252-subject anthropometric dataset
    (Journal of Statistics Education, Johnson 1996).
  - Waist-to-Height Ratio                   (Ashwell & Hsieh, 2005)
  - Waist-to-Hip Ratio                      (WHO, 2008 report)
  - FFMI / normalized FFMI                  (Kouri et al., Am J Sports Med, 1995)
  - Shoulder-to-Waist & Bicep-to-Wrist ratios are informal, traditional
    strength-training/aesthetics heuristics, not clinical measures -- they
    are labeled as such everywhere they appear.
"""

import math

# ---------------------------------------------------------------------------
# Unit conversion registry
# Every measurement in the app is a (value, unit) pair. This registry is the
# single source of truth for converting between the two length units
# ("in", "cm") and two mass units ("lb", "kg") the GUI offers per-field.
# ---------------------------------------------------------------------------

CM_PER_IN = 2.54
CM_TO_IN = 1 / CM_PER_IN
KG_TO_LB = 2.20462262185
LB_TO_KG = 1 / KG_TO_LB

LENGTH_UNITS = ("in", "cm")
MASS_UNITS = ("lb", "kg")


def cm_to_in(cm):
    return None if cm is None else cm * CM_TO_IN


def in_to_cm(inches):
    return None if inches is None else inches * CM_PER_IN


def kg_to_lb(kg):
    return None if kg is None else kg * KG_TO_LB


def lb_to_kg(lb):
    return None if lb is None else lb * LB_TO_KG


def convert_length(value, from_unit, to_unit):
    """Convert a length between 'in' and 'cm'. Returns None if value is None."""
    if value is None:
        return None
    if from_unit == to_unit:
        return value
    if from_unit == "cm" and to_unit == "in":
        return cm_to_in(value)
    if from_unit == "in" and to_unit == "cm":
        return in_to_cm(value)
    raise ValueError(f"Unsupported length units: {from_unit} -> {to_unit}")


def convert_mass(value, from_unit, to_unit):
    """Convert a mass between 'lb' and 'kg'. Returns None if value is None."""
    if value is None:
        return None
    if from_unit == to_unit:
        return value
    if from_unit == "kg" and to_unit == "lb":
        return kg_to_lb(value)
    if from_unit == "lb" and to_unit == "kg":
        return lb_to_kg(value)
    raise ValueError(f"Unsupported mass units: {from_unit} -> {to_unit}")


def to_inches(value, unit):
    return convert_length(value, unit, "in")


def to_cm(value, unit):
    return convert_length(value, unit, "cm")


def to_lb(value, unit):
    return convert_mass(value, unit, "lb")


def to_kg(value, unit):
    return convert_mass(value, unit, "kg")


# Which "kind" of unit each measurement field uses -- the GUI uses this to
# decide whether to show an in/cm toggle or an lb/kg toggle for a field.
LENGTH_FIELDS = ("height", "neck", "chest", "shoulders", "waist", "hip",
                  "thigh", "knee", "ankle", "biceps", "forearm", "wrist", "calf")
MASS_FIELDS = ("weight",)


def field_kind(key):
    if key in LENGTH_FIELDS:
        return "length"
    if key in MASS_FIELDS:
        return "mass"
    return None


# ---------------------------------------------------------------------------
# Individual %BF methods
# All circumference / height args are in INCHES, weight in POUNDS,
# age in years, sex is 'M' or 'F'.
# ---------------------------------------------------------------------------

def navy_method(sex, height, neck, waist, hip=None):
    """US Navy / DoD circumference method. hip only required for females."""
    if None in (height, neck, waist):
        return None
    if sex == 'M':
        val = waist - neck
        if val <= 0:
            return None
        return 86.010 * math.log10(val) - 70.041 * math.log10(height) + 36.76
    else:
        if hip is None:
            return None
        val = waist + hip - neck
        if val <= 0:
            return None
        return 163.205 * math.log10(val) - 97.684 * math.log10(height) - 78.387


def ymca_method(sex, weight, waist):
    """YMCA method. Waist in inches, weight in pounds."""
    if weight is None or not waist:
        return None
    if sex == 'M':
        return ((4.15 * waist - 0.082 * weight - 98.42) / weight) * 100
    else:
        return ((4.15 * waist - 0.082 * weight - 76.76) / weight) * 100


def covert_bailey_method(sex, age, waist=None, hip=None, forearm=None, wrist=None,
                          thigh=None, calf=None):
    """
    Covert Bailey method ("The Ultimate Fit or Fat", 1999).
    Men need: waist, hip, forearm, wrist.
    Women need: hip, thigh, calf, wrist.
    All measurements in inches.
    """
    if sex == 'M':
        if None in (waist, hip, forearm, wrist):
            return None
        coeff = 3.0 if age <= 30 else 2.7
        return waist + 0.5 * hip - coeff * forearm - wrist
    else:
        if None in (hip, thigh, calf, wrist):
            return None
        thigh_coeff = 0.8 if age <= 30 else 1.0
        return hip + thigh_coeff * thigh - 2 * calf - wrist


def katch_mcardle_method(sex, age, abdomen=None, thigh=None, forearm=None,
                          calf=None, biceps=None, hip=None):
    """
    Katch-McArdle circumference method (1983).
    Younger (<=26) vs older (>26) formulas, sex-specific sites.
    All measurements in inches.
    """
    if sex == 'F':
        if age <= 26:
            if None in (abdomen, thigh, forearm):
                return None
            return (abdomen * 1.34) + (thigh * 2.08) - (forearm * 4.31) - 19.6
        else:
            if None in (abdomen, thigh, calf):
                return None
            return (abdomen * 1.19) + (thigh * 1.24) - (calf * 1.45) - 18.4
    else:
        if age <= 26:
            if None in (biceps, abdomen, forearm):
                return None
            return (biceps * 3.70) + (abdomen * 1.31) - (forearm * 5.43) - 10.2
        else:
            if None in (hip, abdomen, forearm):
                return None
            return (hip * 1.05) + (abdomen * 0.90) - (forearm * 3.00) - 15.0


def bmi_method(sex, age, bmi):
    """Deurenberg formula (Deurenberg, Weststrate & Seidell, Br J Nutr 1991):
    BF% = 1.20*BMI + 0.23*age - 10.8*sex - 5.4  (sex: male=1, female=0).
    No tape measure required at all -- used here purely as a sanity-check
    cross-reference point alongside the circumference-based methods."""
    if bmi is None or age is None:
        return None
    sex_val = 1 if sex == 'M' else 0
    return 1.20 * bmi + 0.23 * age - 10.8 * sex_val - 5.4


# ---------------------------------------------------------------------------
# Multi-Site Regression method (13 variables)
# Coefficients fit by OLS against the public Penrose/Nelson/Fisher (1985)
# dataset of 252 adult men (Siri %BF as target). height/weight in in/lb,
# all circumferences in CM (as originally recorded in the source dataset).
# NOTE: because the source population is adult men, this method is only
# offered for male users; results for other body types are unvalidated.
# R^2 = 0.744, RMSE = 4.19 %BF-points on the training data.
# ---------------------------------------------------------------------------

_REGRESSION_INTERCEPT = -18.100372428396273
_REGRESSION_COEFS = {
    "age": 0.06359,
    "weight_lb": -0.08947,
    "height_in": -0.05989,
    "neck_cm": -0.47376,
    "chest_cm": -0.03227,
    "abdomen_cm": 0.95514,
    "hip_cm": -0.19201,
    "thigh_cm": 0.23109,
    "knee_cm": 0.01457,
    "ankle_cm": 0.16728,
    "biceps_cm": 0.19214,
    "forearm_cm": 0.44409,
    "wrist_cm": -1.66864,
}


def multi_site_regression_method(sex, age, weight_lb, height_in, neck_cm, chest_cm,
                                  abdomen_cm, hip_cm, thigh_cm, knee_cm, ankle_cm,
                                  biceps_cm, forearm_cm, wrist_cm):
    """13-variable regression estimator (male-calibrated). Returns None for
    non-male sex or if any required measurement is missing."""
    if sex != 'M':
        return None
    vals = dict(age=age, weight_lb=weight_lb, height_in=height_in, neck_cm=neck_cm,
                chest_cm=chest_cm, abdomen_cm=abdomen_cm, hip_cm=hip_cm,
                thigh_cm=thigh_cm, knee_cm=knee_cm, ankle_cm=ankle_cm,
                biceps_cm=biceps_cm, forearm_cm=forearm_cm, wrist_cm=wrist_cm)
    if any(v is None for v in vals.values()):
        return None
    total = _REGRESSION_INTERCEPT
    for k, coef in _REGRESSION_COEFS.items():
        total += coef * vals[k]
    return total


# ---------------------------------------------------------------------------
# Method ordering / defaults -- used by the GUI to render method checkboxes.
# ---------------------------------------------------------------------------
METHOD_ORDER = [
    "US Navy Method",
    "YMCA Method",
    "Covert Bailey Method",
    "Katch-McArdle Method",
    "BMI-Based Method",
    "Multi-Site Regression (13-var)",
]

DEFAULT_ENABLED_METHODS = METHOD_ORDER.copy()


# ---------------------------------------------------------------------------
# Master runner -- takes a dict of measurements ALREADY IN inches/lb
# and returns (results_dict, bmi).
# ---------------------------------------------------------------------------

def run_all_methods(m):
    """
    m is a dict that may contain (all optional except sex/age/height_in/weight_lb):
        sex ('M'/'F'), age, height_in, weight_lb,
        neck, chest, waist, hip, thigh, knee, ankle, biceps, forearm, wrist, calf
    (all circumferences in inches). 'shoulders' is accepted but ignored here --
    it only feeds the physique-analysis functions below, not any %BF formula.
    """
    sex = m['sex']
    age = m['age']
    height = m['height_in']
    weight = m['weight_lb']

    results = {}

    results['US Navy Method'] = navy_method(
        sex, height, m.get('neck'), m.get('waist'), m.get('hip'))

    results['YMCA Method'] = ymca_method(sex, weight, m.get('waist'))

    results['Covert Bailey Method'] = covert_bailey_method(
        sex, age, waist=m.get('waist'), hip=m.get('hip'),
        forearm=m.get('forearm'), wrist=m.get('wrist'),
        thigh=m.get('thigh'), calf=m.get('calf'))

    results['Katch-McArdle Method'] = katch_mcardle_method(
        sex, age, abdomen=m.get('waist'), thigh=m.get('thigh'),
        forearm=m.get('forearm'), calf=m.get('calf'),
        biceps=m.get('biceps'), hip=m.get('hip'))

    bmi = compute_bmi(weight, height)
    results['BMI-Based Method'] = bmi_method(sex, age, bmi)

    def _to_cm(x):
        return None if x is None else x * CM_PER_IN

    results['Multi-Site Regression (13-var)'] = multi_site_regression_method(
        sex, age, weight, height,
        _to_cm(m.get('neck')), _to_cm(m.get('chest')), _to_cm(m.get('waist')),
        _to_cm(m.get('hip')), _to_cm(m.get('thigh')), _to_cm(m.get('knee')),
        _to_cm(m.get('ankle')), _to_cm(m.get('biceps')), _to_cm(m.get('forearm')),
        _to_cm(m.get('wrist')))

    return results, bmi


def filter_results(results, enabled_methods=None):
    """Return {method: value} restricted to enabled_methods (defaults to all
    methods present) and to entries whose value is not None."""
    if enabled_methods is None:
        enabled_methods = list(results.keys())
    return {k: v for k, v in results.items() if k in enabled_methods and v is not None}


def average_body_fat(results, enabled_methods=None):
    """Average of the enabled, non-None %BF results, or None if none apply."""
    valid = filter_results(results, enabled_methods)
    if not valid:
        return None
    return sum(valid.values()) / len(valid)


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def compute_bmi(weight_lb, height_in):
    if weight_lb is None or not height_in:
        return None
    return (weight_lb / (height_in ** 2)) * 703


def fat_free_mass(weight, bf_pct):
    """weight in whatever unit -- returns same unit."""
    if weight is None or bf_pct is None:
        return None
    return weight * (1 - bf_pct / 100)


def fat_mass(weight, bf_pct):
    if weight is None or bf_pct is None:
        return None
    return weight * (bf_pct / 100)


# Upper-bound thresholds (ACE body fat categories). Using continuous
# upper-only cutoffs avoids gaps for fractional %BF values.
CATEGORY_BOUNDS = {
    'M': [
        (5, "Essential Fat"),
        (13, "Athletes"),
        (17, "Fitness"),
        (24, "Average"),
    ],  # anything above the last cutoff -> "Obese"
    'F': [
        (13, "Essential Fat"),
        (20, "Athletes"),
        (24, "Fitness"),
        (31, "Average"),
    ],
}


def classify(sex, bf_pct):
    if bf_pct is None:
        return None
    for hi, label in CATEGORY_BOUNDS[sex]:
        if bf_pct <= hi:
            return label
    return "Obese"


# ---------------------------------------------------------------------------
# Physique-analysis ratios
# All functions here take INCHES (any length unit already normalized by the
# caller) and return None gracefully if inputs are missing, so the analysis
# degrades gracefully when only some tape measurements were taken.
# ---------------------------------------------------------------------------

def waist_to_height_ratio(waist_in, height_in):
    if not waist_in or not height_in:
        return None
    return waist_in / height_in


# Ashwell & Hsieh (2005): "keep your waist circumference to less than half
# your height" -- 0.5 is the headline cutoff; bands below add resolution.
WHTR_BANDS = [
    (0.40, "Very Lean"),
    (0.50, "Healthy"),
    (0.58, "Increased Risk"),
    (0.63, "High Risk"),
]  # above the last cutoff -> "Very High Risk"


def classify_whtr(whtr):
    if whtr is None:
        return None
    for hi, label in WHTR_BANDS:
        if whtr <= hi:
            return label
    return "Very High Risk"


def waist_to_hip_ratio(waist_in, hip_in):
    if not waist_in or not hip_in:
        return None
    return waist_in / hip_in


# WHO (2008) "Waist Circumference and Waist-Hip Ratio" report thresholds.
WHR_BANDS = {
    'M': [(0.90, "Low Risk"), (0.99, "Moderate Risk")],
    'F': [(0.80, "Low Risk"), (0.84, "Moderate Risk")],
}  # above the last cutoff -> "High Risk"


def classify_whr(sex, whr):
    if whr is None:
        return None
    for hi, label in WHR_BANDS[sex]:
        if whr <= hi:
            return label
    return "High Risk"


def shoulder_to_waist_ratio(shoulder_in, waist_in):
    if not shoulder_in or not waist_in:
        return None
    return shoulder_in / waist_in


# Informal strength-training / aesthetics heuristic ("Adonis Index"-style
# V-taper). 1.618 (the golden ratio) is the commonly-cited aspirational
# target in fitness media -- NOT a clinical or scientific benchmark.
VTAPER_BANDS = [
    (1.3, "Emerging Taper"),
    (1.5, "Good Taper"),
    (1.65, "Strong V-Taper"),
]  # above the last cutoff -> "Exceptional V-Taper"


def classify_vtaper(ratio):
    if ratio is None:
        return None
    for hi, label in VTAPER_BANDS:
        if ratio <= hi:
            return label
    return "Exceptional V-Taper"


def bicep_to_wrist_ratio(biceps_in, wrist_in):
    if not biceps_in or not wrist_in:
        return None
    return biceps_in / wrist_in


# Another informal, traditional strength-training heuristic relating arm
# size to wrist (frame) size -- not a clinical measure.
ARM_BANDS = [
    (1.8, "Developing"),
    (2.1, "Balanced"),
    (2.5, "Well-Developed"),
]  # above the last cutoff -> "Exceptional"


def classify_arm_ratio(ratio):
    if ratio is None:
        return None
    for hi, label in ARM_BANDS:
        if ratio <= hi:
            return label
    return "Exceptional"


def ffmi(weight_lb, height_in, bf_pct):
    """Fat-Free Mass Index and height-normalized FFMI
    (Kouri et al., Am J Sports Med, 1995). Returns (ffmi, normalized_ffmi)
    or (None, None) if inputs are missing."""
    if weight_lb is None or not height_in or bf_pct is None:
        return None, None
    weight_kg = lb_to_kg(weight_lb)
    height_m = height_in * CM_PER_IN / 100
    ffm_kg = weight_kg * (1 - bf_pct / 100)
    value = ffm_kg / (height_m ** 2)
    normalized = value + 6.1 * (1.8 - height_m)
    return value, normalized


# ---------------------------------------------------------------------------
# Composite Body Score (0-100)
# A transparent, weighted blend of body-fat %, waist-to-height ratio, and
# waist-to-hip ratio. This is a fun, informal composite for tracking your
# own trend over time -- NOT a medical or diagnostic score. Components with
# missing inputs are simply dropped and the remaining weights re-normalized,
# so a partial measurement set still produces a sensible score.
# ---------------------------------------------------------------------------

# (low, peak_low, peak_high, high) target windows for %BF by sex -- score is
# 1.0 between peak_low/peak_high, ramping to 0 at low/high.
BF_TARGET_WINDOW = {
    'M': dict(low=3, peak_low=8, peak_high=18, high=30),
    'F': dict(low=10, peak_low=16, peak_high=27, high=38),
}


def _triangular_score(x, low, peak_low, peak_high, high):
    if x is None:
        return None
    if x <= low or x >= high:
        return 0.0
    if x < peak_low:
        return (x - low) / (peak_low - low)
    if x > peak_high:
        return (high - x) / (high - peak_high)
    return 1.0


def _whtr_score(whtr):
    if whtr is None:
        return None
    if whtr <= 0.5:
        return 1.0
    if whtr >= 0.65:
        return 0.0
    return (0.65 - whtr) / (0.65 - 0.5)


def _whr_score(sex, whr):
    if whr is None:
        return None
    good = 0.90 if sex == 'M' else 0.80
    bad = 1.05 if sex == 'M' else 0.95
    if whr <= good:
        return 1.0
    if whr >= bad:
        return 0.0
    return (bad - whr) / (bad - good)


def compute_body_score(sex, avg_bf, whtr=None, whr=None):
    """Returns (score_0_100_or_None, breakdown_list). breakdown_list has one
    dict per component actually used: {"component", "weight", "score_pct"}."""
    components = []

    if avg_bf is not None:
        bf_score = _triangular_score(avg_bf, **BF_TARGET_WINDOW[sex])
        components.append(("Body Fat %", 0.40, bf_score))

    whtr_score = _whtr_score(whtr)
    if whtr_score is not None:
        components.append(("Waist-to-Height Ratio", 0.30, whtr_score))

    whr_score = _whr_score(sex, whr)
    if whr_score is not None:
        components.append(("Waist-to-Hip Ratio", 0.30, whr_score))

    if not components:
        return None, []

    total_weight = sum(w for _, w, _ in components)
    weighted = sum(w * s for _, w, s in components)
    score = round((weighted / total_weight) * 100)
    breakdown = [
        {"component": name, "weight": round(w / total_weight, 3), "score_pct": round(s * 100)}
        for name, w, s in components
    ]
    return score, breakdown


# ---------------------------------------------------------------------------
# Physique analysis orchestrator
# ---------------------------------------------------------------------------

def physique_analysis(sex, m, avg_bf):
    """
    m: canonical dict with keys height_in, weight_lb, and (optionally) neck,
       chest, shoulders, waist, hip, thigh, knee, ankle, biceps, forearm,
       wrist, calf -- all in inches or None.
    avg_bf: the averaged %BF across enabled methods, or None.

    Returns a dict with every computed ratio/category, the Body Score and
    its breakdown, and short "strengths" / "watch_areas" text lists.
    """
    whtr = waist_to_height_ratio(m.get('waist'), m.get('height_in'))
    whtr_cat = classify_whtr(whtr)

    whr = waist_to_hip_ratio(m.get('waist'), m.get('hip'))
    whr_cat = classify_whr(sex, whr)

    vtaper = shoulder_to_waist_ratio(m.get('shoulders'), m.get('waist'))
    vtaper_cat = classify_vtaper(vtaper)

    arm_ratio = bicep_to_wrist_ratio(m.get('biceps'), m.get('wrist'))
    arm_cat = classify_arm_ratio(arm_ratio)

    ffmi_val, ffmi_norm = ffmi(m.get('weight_lb'), m.get('height_in'), avg_bf)

    score, breakdown = compute_body_score(sex, avg_bf, whtr, whr)

    strengths, watch_areas = [], []

    if whtr_cat in ("Very Lean", "Healthy"):
        strengths.append(f"Waist-to-height ratio ({whtr:.2f}) is in the healthy range.")
    elif whtr_cat is not None:
        watch_areas.append(
            f"Waist-to-height ratio ({whtr:.2f}) is elevated ({whtr_cat.lower()}) -- "
            "central body fat is a good area to focus on.")

    if whr_cat == "Low Risk":
        strengths.append(f"Waist-to-hip ratio ({whr:.2f}) suggests low central-fat health risk.")
    elif whr_cat is not None:
        watch_areas.append(
            f"Waist-to-hip ratio ({whr:.2f}) suggests {whr_cat.lower()} -- "
            "more overall/core fat loss could help here.")

    if vtaper_cat in ("Strong V-Taper", "Exceptional V-Taper"):
        strengths.append(f"Shoulder-to-waist ratio ({vtaper:.2f}) shows a strong V-taper.")
    elif vtaper_cat is not None:
        watch_areas.append(
            f"Shoulder-to-waist ratio ({vtaper:.2f}) is still developing -- "
            "shoulder/back training or waist reduction would improve it.")

    if arm_cat in ("Well-Developed", "Exceptional"):
        strengths.append(f"Bicep-to-wrist ratio ({arm_ratio:.2f}) shows well-developed arm size for your frame.")
    elif arm_cat is not None:
        watch_areas.append(
            f"Bicep-to-wrist ratio ({arm_ratio:.2f}) suggests room to build arm size relative to your frame.")

    bf_category = classify(sex, avg_bf) if avg_bf is not None else None
    if bf_category in ("Athletes", "Fitness"):
        strengths.append(f"Body fat % ({avg_bf:.1f}%) falls in the {bf_category} range.")
    elif bf_category == "Obese":
        watch_areas.append(f"Body fat % ({avg_bf:.1f}%) is in the higher range -- the biggest lever for your Body Score.")

    return {
        "whtr": whtr, "whtr_category": whtr_cat,
        "whr": whr, "whr_category": whr_cat,
        "shoulder_to_waist": vtaper, "shoulder_to_waist_category": vtaper_cat,
        "bicep_to_wrist": arm_ratio, "bicep_to_wrist_category": arm_cat,
        "ffmi": ffmi_val, "ffmi_normalized": ffmi_norm,
        "body_score": score, "body_score_breakdown": breakdown,
        "strengths": strengths, "watch_areas": watch_areas,
    }