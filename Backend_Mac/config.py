import math

# --- TASARIM VE RENKLER ---
COLORS = {
    "BG": "#121212", "PANEL": "#f5f6fa", "BLUE": "#00a8ff", 
    "GREEN": "#4cd137", "YELLOW": "#fbc531", "RED": "#e84118", 
    "WHITE": "#ffffff", "GRAY": "#444444", "BTN_TEXT": "#000000"
}

# --- SİSTEM PARAMETRELERİ ---
PARAMS = {
    "MAX_ILAC": 100, 
    "HIZ_TRANSIT_KMH": 30, 
    "HIZ_ILACLAMA_KMH": 10,
    "ILAC_DONUM_BASI": 2.0, 
    "PIL_DONUM_BASI": 2.0, 
    "PIL_KM_BASI": 2, 
    "SANIYE_PER_DONUM": 60 
}

# --- DÜNYA KOORDİNAT MESAFE HESAPLAYICI ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))