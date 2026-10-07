CREATE TABLE IF NOT EXISTS gesec_facture_gm_pred (
    identifiant_chorus_pro TEXT PRIMARY KEY,
    ministere TEXT,
    gm TEXT,
    gm_pred TEXT,
    gm_pred_domaine TEXT,
    gm_pred_segment TEXT,
    gm_pred_raison TEXT,
    gm_pred_raw JSONB,
    gm_pred_at TIMESTAMPTZ,
    gm_pred_model TEXT,
    latency_s NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_gesec_facture_gm_pred_ministere ON gesec_facture_gm_pred (ministere);
CREATE INDEX IF NOT EXISTS idx_gesec_facture_gm_pred_gm ON gesec_facture_gm_pred (gm);
CREATE INDEX IF NOT EXISTS idx_gesec_facture_gm_pred_gm_pred ON gesec_facture_gm_pred (gm_pred);