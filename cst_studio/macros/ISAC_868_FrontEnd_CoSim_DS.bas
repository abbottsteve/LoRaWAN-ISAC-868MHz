' =============================================================================
' ISAC_868_FrontEnd_CoSim_DS.bas
' CST Design Studio (DS) Schematic Co-Simulation Macro for ISAC_868 Rev E.5
'
' Purpose:
'   When the 3D Microwave Studio model is solved in Mode 0 (`excitation_mode = 0`,
'   direct port at AE1 Pad 1 `/ANT_FEED`), this CST Design Studio schematic script
'   documents and sets up the full RF front-end co-simulation chain:
'     Port 1 (`SX1262 RFO_LP + C_RF=100pF`, 50 Ohm)
'       -> Asymmetric Return-Loss Bridge:
'            R1 = 8.2 Ohm (0.1% Yageo RT0402BRD078R2L)
'            R2 = 681 Ohm, R3 = 3.57 kOhm (/BR_S C_par = 0.1305 pF over 2.2x2.2 mm void)
'            C_S = C_S2 = 1.0 pF, L_Q = 27 nH, L_S = 30 nH, R_TERM = 56 Ohm
'       -> Coupled Detector Port 2 (`LT5538IDD#TRPBF` IN+ = 291.65 Ohm || 1.194 pF)
'       -> 4-Element Elliptic Harmonic Pi-Filter (`C_M1=3.6p, L_M1=8.2n||C_MZ=0.5p, C_M2=4.3p`
'            or drop-in Murata SimSurfing .s2p blocks)
'       -> 3D CST MWS Antenna Block (`AE1 + Enclosure + Debye Superstrate`).
'
' This enables instantaneous Monte-Carlo tolerance sweeps & Murata .s2p substitution
' in CST Design Studio without re-running the 3D field solver.
' =============================================================================

Option Explicit

Sub Main()
    ' Store RF Front-End schematic parameters in the Design Studio workspace
    StoreDoubleParameter "DS_R1_ohm", 8.20
    StoreDoubleParameter "DS_R2_ohm", 681.0
    StoreDoubleParameter "DS_R3_ohm", 3570.0
    StoreDoubleParameter "DS_RTERM_ohm", 56.0
    StoreDoubleParameter "DS_CS_pf", 1.00
    StoreDoubleParameter "DS_CS2_pf", 1.00
    StoreDoubleParameter "DS_CPAR_BRS_pf", 0.1305
    StoreDoubleParameter "DS_LQ_nh", 27.0
    StoreDoubleParameter "DS_LS_nh", 30.0
    StoreDoubleParameter "DS_RLT5538_ohm", 291.65
    StoreDoubleParameter "DS_CLT5538_pf", 1.194
    StoreDoubleParameter "DS_CM1_pf", 3.60
    StoreDoubleParameter "DS_LM1_nh", 8.20
    StoreDoubleParameter "DS_CMZ_pf", 0.50
    StoreDoubleParameter "DS_CM2_pf", 4.30

    MsgBox "CST Design Studio (DS) Rev E.5 Bridge + Elliptic Filter + LT5538 parameters registered." & vbCrLf & _
           "Connect Port 1 of the 3D MWS block (solved with excitation_mode=0) to C_M2/L_M1 on the DS canvas, " & _
           "or run python/postprocess_cst_results.py on exported .s1p files for automated 2,000-trial MC & 3-tone analysis.", _
           vbInformation
End Sub
