import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List
import math
import random
import time
from pathlib import Path

app = FastAPI(title="Ragnarok Drop Simulator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "drops.json"

if not DATA_FILE.exists():
    raise RuntimeError(f"Arquivo de dados não encontrado: {DATA_FILE}")

with DATA_FILE.open("r", encoding="utf-8") as f:
    DATA = json.load(f)

# ----------------------------
# CONSUMÍVEIS — REGRAS NOVAS
# ----------------------------

# Grupo 1 — "maior bônus vence" (GERAL)
BIG_CONS = {
    "calice": 265.0,
    "calice2": 240.0,
    "chicle": 200.0,
    "chiclete": 100.0,
}

# Consumíveis gerais SOMADOS condicionalmente
GENERAL_CONS = {
    "lata": 20.0,            # +20% (não funciona com cálice/cálice2)
    "revitalizadora": 20.0,  # +20% (não funciona com cálice/cálice2)
    "drop_pot": 25.0,        # +25% (não funciona com cálice)
    "fusion": 25.0,          # sempre soma
    "doador": 35.0,          # sempre soma
    "doador_rmt": 35.0,      # sempre soma
}

# Consumíveis de BÔNUS FINAL (multiplicativo)
FINAL_CONS = {
    "black": 6.0,
    "ativador": 5.0,
    "carnavalesco": 2.0,
    "champs": 6.0,
    "amantes": 4.0,
}


class Scenario(BaseModel):
    general_mods: Dict[str, float]
    final_mods: Dict[str, float]
    consumables: List[str]


class BatchCalculateRequest(BaseModel):
    content_id: str
    level_id: str
    general_mods: Dict[str, float]
    final_mods: Dict[str, float]
    consumables: List[str]


# ============================================================
# NOVOS ENDPOINTS — Seleção de Conteúdo, Nível e Drops
# ============================================================

@app.get("/contents")
def list_contents():
    """Retorna lista de todos os conteúdos disponíveis"""
    contents = DATA.get("contents", {})
    result = []
    for content_id, content_data in contents.items():
        result.append({
            "content_id": content_id,
            "name": content_data.get("name", content_id),
            "type": content_data.get("type", "normal")
        })
    return {"contents": result}


@app.get("/contents/{content_id}/levels")
def list_levels(content_id: str):
    """Retorna lista de níveis para um conteúdo específico"""
    contents = DATA.get("contents", {})
    if content_id not in contents:
        raise HTTPException(status_code=404, detail="Content not found")
    
    content = contents[content_id]
    levels = content.get("levels", {})
    result = []
    
    for level_num, level_data in levels.items():
        result.append({
            "level_id": level_num,
            "name": level_data.get("name", f"Level {level_num}")
        })
    
    # Ordena pelos níveis numéricos
    result.sort(key=lambda x: int(x["level_id"]))
    return {"levels": result}


@app.get("/contents/{content_id}/levels/{level_id}/drops")
def list_drops(content_id: str, level_id: str):
    """Retorna lista de drops disponíveis para um nível específico"""
    contents = DATA.get("contents", {})
    if content_id not in contents:
        raise HTTPException(status_code=404, detail="Content not found")
    
    content = contents[content_id]
    levels = content.get("levels", {})
    if level_id not in levels:
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = levels[level_id]
    drop_ids = level.get("drops", [])
    items = DATA.get("items", {})
    
    result = []
    for item_id in drop_ids:
        if item_id in items:
            item = items[item_id]
            result.append({
                "item_id": item_id,
                "name": item.get("name", item_id),
                "base_drop_percent": item.get("base_drop_percent", 0.0)
            })
    
    return {"drops": result}

@app.get("/contents/{content_id}/levels/{level_id}/monster-drops")
def list_monster_drops(content_id: str, level_id: str):
    """Retorna tabela de drops por monstro para conteúdos tipo monster_table"""
    contents = DATA.get("contents", {})
    if content_id not in contents:
        raise HTTPException(status_code=404, detail="Content not found")
    
    content = contents[content_id]
    
    # Verifica se é do tipo monster_table
    if content.get("type") != "monster_table":
        raise HTTPException(status_code=400, detail="This content type doesn't support monster tables")
    
    levels = content.get("levels", {})
    if level_id not in levels:
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = levels[level_id]
    monsters = level.get("monsters", [])
    drops_data = level.get("drops", {})
    items = DATA.get("items", {})
    
    # Monta os dados dos monstros
    monster_info = []
    for monster_id in monsters:
        monster_info.append({
            "monster_id": monster_id,
            "name": monster_id.replace("_", " ").title()
        })
    
    # Monta os dados dos drops
    drops_info = []
    for item_id, monster_rates in drops_data.items():
        if item_id in items:
            item = items[item_id]
            drop_entry = {
                "item_id": item_id,
                "item_name": item.get("name", item_id),
                "rates": {}
            }
            
            # Adiciona a taxa para cada monstro
            for monster_id in monsters:
                drop_entry["rates"][monster_id] = monster_rates.get(monster_id, 0.0)
            
            drops_info.append(drop_entry)
    
    return {
        "content_id": content_id,
        "level_id": level_id,
        "monsters": monster_info,
        "drops": drops_info
    }

@app.post("/drop/calculate-all")
def calculate_all_drops(req: BatchCalculateRequest):
    """Calcula taxas finais para TODOS os drops de um nível"""
    contents = DATA.get("contents", {})
    if req.content_id not in contents:
        raise HTTPException(status_code=404, detail="Content not found")
    
    content = contents[req.content_id]
    levels = content.get("levels", {})
    if req.level_id not in levels:
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = levels[req.level_id]
    drop_ids = level.get("drops", [])
    items = DATA.get("items", {})
    
    # Processa consumíveis uma vez
    selected = set(req.consumables)
    
    # 1 — maior bônus dos 4 principais
    best_big = max((BIG_CONS[c] for c in selected if c in BIG_CONS), default=0.0)
    
    general_mods = dict(req.general_mods) if req.general_mods else {}
    if best_big > 0:
        general_mods["consumable_big"] = best_big
    
    # flags
    used_calice = "calice" in selected
    used_calice2 = "calice2" in selected
    used_big = used_calice or used_calice2
    
    # 2 — consumíveis gerais SOMADOS com regras
    for key, val in GENERAL_CONS.items():
        if key not in selected:
            continue
        
        if key in ("lata", "revitalizadora"):
            if not used_big:
                general_mods[key] = val
        elif key == "drop_pot":
            if not used_calice:
                general_mods[key] = val
        else:
            general_mods[key] = val
    
    # 3 — consumíveis finais sempre somam
    final_mods = dict(req.final_mods) if req.final_mods else {}
    for key, val in FINAL_CONS.items():
        if key in selected:
            final_mods[f"final_{key}"] = val

    # Lógica condicional da reputação domínio
     # Só aplica se for conteúdo dominio
    if req.content_id == "dominio":
        # Mantém o bônus que veio do frontend
        pass
    else:
        # Remove o bônus se não for domínio
        if "dominio_reputation" in general_mods:
            del general_mods["dominio_reputation"]
            
    
    # Calcula para cada item
    B_general = sum(general_mods.values())
    B_final = sum(final_mods.values())
    
    result = []
    for item_id in drop_ids:
        if item_id in items:
            item = items[item_id]
            p_base = float(item.get("base_drop_percent", 0.0))
            is_florzinha = item.get("is_florzinha", False)

            p_inter = p_base * (1 + B_general / 100.0)
            p_final = p_inter * (1 + B_final / 100.0)
            p_final = apply_caps(p_base, p_final)
            
            result.append({
                "item_id": item_id,
                "item_name": item.get("name", item_id),
                "base_drop_percent": p_base,
                "B_general_percent": B_general,
                "B_final_percent": B_final,
                "p_inter_percent": p_inter,
                "p_final_percent": p_final,
                "is_florzinha": is_florzinha
            })
    
    return {
        "content_id": req.content_id,
        "level_id": req.level_id,
        "B_general_percent": B_general,
        "B_final_percent": B_final,
        "drops": result
    }


def apply_caps(p_base_percent: float, p_final_percent: float) -> float:
    if p_base_percent <= 90:
        return min(p_final_percent, 90.0)
    elif p_base_percent == 100:
        return 100.0
    return p_final_percent

@app.post("/drop/calculate-monster-table")
def calculate_monster_table(req: BatchCalculateRequest):
    """Calcula taxas finais para todos os drops de um nível tipo monster_table"""
    contents = DATA.get("contents", {})
    if req.content_id not in contents:
        raise HTTPException(status_code=404, detail="Content not found")
    
    content = contents[req.content_id]
    
    if content.get("type") != "monster_table":
        raise HTTPException(status_code=400, detail="This content type doesn't support monster tables")
    
    levels = content.get("levels", {})
    if req.level_id not in levels:
        raise HTTPException(status_code=404, detail="Level not found")
    
    level = levels[req.level_id]
    monsters = level.get("monsters", [])
    drops_data = level.get("drops", {})
    items = DATA.get("items", {})
    
    # Processa consumíveis
    selected = set(req.consumables)
    best_big = max((BIG_CONS[c] for c in selected if c in BIG_CONS), default=0.0)
    
    general_mods = dict(req.general_mods) if req.general_mods else {}
    if best_big > 0:
        general_mods["consumable_big"] = best_big
    
    used_calice = "calice" in selected
    used_calice2 = "calice2" in selected
    used_big = used_calice or used_calice2
    
    for key, val in GENERAL_CONS.items():
        if key not in selected:
            continue
        if key in ("lata", "revitalizadora"):
            if not used_big:
                general_mods[key] = val
        elif key == "drop_pot":
            if not used_calice:
                general_mods[key] = val
        else:
            general_mods[key] = val
    
    final_mods = dict(req.final_mods) if req.final_mods else {}
    for key, val in FINAL_CONS.items():
        if key in selected:
            final_mods[f"final_{key}"] = val
    

    # Só aplica se for conteúdo dominio
    if req.content_id == "dominio":
        # Mantém o bônus que veio do frontend
        pass
    else:
        # Remove o bônus se não for domínio
        if "dominio_reputation" in general_mods:
            del general_mods["dominio_reputation"]



    

    B_general = sum(general_mods.values())
    B_final = sum(final_mods.values())
    
    # Calcula para cada item e monstro
    monster_info = [{"monster_id": m, "name": m.replace("_", " ").title()} for m in monsters]
    
    result_drops = []
    for item_id, monster_rates in drops_data.items():
        if item_id in items:
            item = items[item_id]
            drop_entry = {
                "item_id": item_id,
                "item_name": item.get("name", item_id),
                "calculated_rates": {}
            }
            
            for monster_id in monsters:
                p_base = float(monster_rates.get(monster_id, 0.0))
                p_inter = p_base * (1 + B_general / 100.0)
                p_final = p_inter * (1 + B_final / 100.0)
                p_final = apply_caps(p_base, p_final)
                
                drop_entry["calculated_rates"][monster_id] = {
                    "base": p_base,
                    "final": p_final
                }
            
            result_drops.append(drop_entry)
    
    return {
        "content_id": req.content_id,
        "level_id": req.level_id,
        "B_general_percent": B_general,
        "B_final_percent": B_final,
        "monsters": monster_info,
        "drops": result_drops
    }

@app.post("/drop/calculate")
def drop_calculate(s: Scenario):
    item = DATA.get("items", {}).get(s.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    p_base = float(item.get("base_drop_percent", 0.0))

    selected = set(s.consumables)
    best_big = max((BIG_CONS[c] for c in selected if c in BIG_CONS), default=0.0)

    if best_big > 0:
        s.general_mods["consumable_big"] = best_big

    used_calice = "calice" in selected
    used_calice2 = "calice2" in selected
    used_big = used_calice or used_calice2

    for key, val in GENERAL_CONS.items():
        if key not in selected:
            continue
        if key in ("lata", "revitalizadora"):
            if not used_big:
                s.general_mods[key] = val
        elif key == "drop_pot":
            if not used_calice:
                s.general_mods[key] = val
        else:
            s.general_mods[key] = val

    for key, val in FINAL_CONS.items():
        if key in selected:
            s.final_mods[f"final_{key}"] = val

    ADV_MASTERY = {"adv_1": 1.0, "adv_2": 3.0, "adv_3": 5.0, "adv_4": 8.0}
    BIRTH_MASTERY = {"birth_1": 1.0, "birth_2": 2.0, "birth_3": 3.0, "birth_4": 5.0}
    REBORN_MASTERY = {"reborn_1": 1.0, "reborn_2": 2.0, "reborn_3": 3.0, "reborn_4": 5.0, "reborn_5": 8.0}

    for key, val in ADV_MASTERY.items():
        if key in selected:
            s.final_mods["adv_mastery"] = val
            break

    for key, val in BIRTH_MASTERY.items():
        if key in selected:
            s.final_mods["birth_mastery"] = val
            break

    for key, val in REBORN_MASTERY.items():
        if key in selected:
            s.final_mods["reborn_mastery"] = val
            break

    B_general = sum(s.general_mods.values()) if s.general_mods else 0.0
    B_final = sum(s.final_mods.values()) if s.final_mods else 0.0

    p_inter = p_base * (1 + B_general / 100.0)
    p_final = p_inter * (1 + B_final / 100.0)
    p_final = apply_caps(p_base, p_final)

    base_flor = 2.0
    flor_inter = base_flor * (1 + B_general / 100.0)
    flor_final = flor_inter * (1 + B_final / 100.0)
    flor_final = apply_caps(base_flor, flor_final)

    p_final_frac = p_final / 100.0
    num_kills = max(1, int(s.num_kills))

    prob_at_least_one = 1 - (1 - p_final_frac) ** num_kills
    expected = num_kills * p_final_frac
    expected_kills_to_one = (1 / p_final_frac) if p_final_frac > 0 else None
    median_kills_50 = (math.log(0.5) / math.log(1 - p_final_frac)) if p_final_frac > 0 else None

    return {
        "item_id": s.item_id,
        "p_base_percent": p_base,
        "B_general_percent": B_general,
        "B_final_percent": B_final,
        "p_inter_percent": p_inter,
        "p_final_percent": p_final,
        "drop_florzinha_percent": flor_final,
        "prob_at_least_one_in_N": prob_at_least_one,
        "expected_drops_in_N": expected,
        "mean_kills_for_one": expected_kills_to_one,
        "median_kills_for_50pct": median_kills_50,
        "num_kills": num_kills,
    }


@app.post("/drop/simulate")
def drop_simulate(s: Scenario):
    calc = drop_calculate(s)
    p_final_frac = calc["p_final_percent"] / 100.0
    sims = max(1, int(s.mc_simulations))
    rng = random.Random(int(time.time() * 1000))

    kills_to_get = []
    MAX_KILLS_PER_SIM = 1_000_000

    for _ in range(sims):
        kills = 0
        got = False
        while not got and kills < MAX_KILLS_PER_SIM:
            kills += 1
            if rng.random() < p_final_frac:
                got = True
        kills_to_get.append(kills)

    kills_to_get.sort()
    median = kills_to_get[len(kills_to_get) // 2]

    def percentile(arr, p):
        idx = int(p / 100.0 * len(arr))
        idx = min(max(0, idx), len(arr) - 1)
        return arr[idx]

    return {
        "simulations": sims,
        "avg_kills": sum(kills_to_get) / len(kills_to_get),
        "median_kills": median,
        "p10": percentile(kills_to_get, 10),
        "p25": percentile(kills_to_get, 25),
        "p75": percentile(kills_to_get, 75),
        "p90": percentile(kills_to_get, 90),
    }