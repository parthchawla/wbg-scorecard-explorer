// Short plain-language labels for WBG Results indicators (full official names come from the API).
export const SHORT: Record<string, string> = {
  CSC_RES_SOC_SAF_PROG: "Social safety net beneficiaries",
  CSC_RES_EDU_SUPP: "Students supported with better education",
  CSC_RES_HEA_SERV: "People receiving quality health services",
  CSC_RES_HEA_EMER_BENE: "Economies better prepared for health emergencies",
  CSC_RES_DEBT_SUST_RISK: "High-debt-risk economies reforming (%)",
  CSC_RES_TAX_REV_GDP: "Low-tax economies raising revenue",
  CSC_RES_RESI_CLIM_RISK: "People more resilient to climate risks",
  CSC_RES_GHG_EMS_YEAR: "Net greenhouse-gas emissions (expected)",
  CSC_RES_TER_AQU_HECT: "Land and water under better conservation",
  CSC_RES_WAT_SAN_HYG_TOT: "People with water, sanitation or hygiene",
  CSC_RES_FOOD_NUTR_SECU: "People with stronger food and nutrition security",
  CSC_RES_ACCS_TRANS_INFRA_SERV: "People with better access to transport",
  CSC_RES_ELC_ACCS: "People given electricity access",
  CSC_RES_REN_ENER_ENAB: "Renewable energy capacity enabled",
  CSC_RES_BRO_INTE: "People using broadband internet",
  CSC_RES_DIG_ENA_SERV: "People using digitally enabled services",
  CSC_RES_GEN_EQU_BENE: "People benefiting from gender-equality actions",
  CSC_RES_FIN_SERV_WOM: "People and businesses using financial services",
  CSC_RES_DISP_COMM_SERVICES: "Displaced people and hosts receiving services",
  CSC_RES_NEW_JOBS_WOM_YOU: "New or better jobs",
  CSC_RES_PRIV_CAP_MOBL: "Private capital mobilized",
  CSC_RES_PRIV_CAP_ENAB: "Private capital enabled",
};

export const shortName = (code: string, fallback = code) => SHORT[code] ?? fallback;

// Client Context indicator that best shows the "need" behind each results indicator.
export const NEED: Record<string, string> = {
  CSC_RES_SOC_SAF_PROG: "PER_ALLSP_COV_POP_TO",
  CSC_RES_EDU_SUPP: "SE_LPV_PRIM",
  CSC_RES_HEA_SERV: "SH_UHC_SRVS_CV_XD",
  CSC_RES_HEA_EMER_BENE: "SH_UHC_SRVS_CV_XD",
  CSC_RES_DEBT_SUST_RISK: "FI_DEB_RISK",
  CSC_RES_TAX_REV_GDP: "FI_TAX_GD_ZS",
  CSC_RES_RESI_CLIM_RISK: "EN_CLM_VULN",
  CSC_RES_GHG_EMS_YEAR: "EN_ATM_GHGT_GT_CE",
  CSC_RES_TER_AQU_HECT: "ER_PTD_TOTL_ZS",
  CSC_RES_WAT_SAN_HYG_TOT: "SH_H2O_STA_HYGN_ZS_TO",
  CSC_RES_FOOD_NUTR_SECU: "SN_ITK_MSFI_ZS_CC",
  CSC_RES_ACCS_TRANS_INFRA_SERV: "SP_ROD_R2KM",
  CSC_RES_ELC_ACCS: "EG_ELC_ACCS_ZS",
  CSC_RES_REN_ENER_ENAB: "EG_ELC_ACCS_ZS",
  CSC_RES_BRO_INTE: "IT_NET_USER_ZS",
  CSC_RES_DIG_ENA_SERV: "IT_GOV_EGOV_XQ",
  CSC_RES_GEN_EQU_BENE: "FX_OWN_TO",
  CSC_RES_FIN_SERV_WOM: "FX_OWN_TO",
  CSC_RES_DISP_COMM_SERVICES: "SM_POP_FDIP",
  CSC_RES_NEW_JOBS_WOM_YOU: "SL_UEM_NEET_ME_TO",
  CSC_RES_PRIV_CAP_MOBL: "NE_GDI_FPRV_ZS",
  CSC_RES_PRIV_CAP_ENAB: "NE_GDI_FPRV_ZS",
};

export const REGION_SHORT: Record<string, string> = {
  AFE: "Eastern & Southern Africa", AFW: "Western & Central Africa", EAP: "East Asia & Pacific",
  ECA: "Europe & Central Asia", LCR: "Latin America & Caribbean", MENAAP: "Middle East, N. Africa, Afg. & Pak.",
  MNA: "Middle East & N. Africa", SAR: "South Asia", OTH: "Other / multi-region", ACW: "All countries",
};
