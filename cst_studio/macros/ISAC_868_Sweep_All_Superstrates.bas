' =============================================================================
' ISAC_868_Sweep_All_Superstrates.bas
' Automated 10-Scenario CST Microwave Studio Batch Sweep & Touchstone Exporter
'
' Executes the exact 10 benchmark configurations matching `rf/ifa_enclosure_mom.py`
' and exports Touchstone v1.1 (.s1p) + 866.5 MHz Farfield ASCII summaries into
' `<project_dir>/../results/` (or `<project_dir>/Export_Results/`) for direct
' ingestion by `cst_studio/python/postprocess_cst_results.py`.
' =============================================================================

Option Explicit

Sub RunCase(ByVal caseTag As String, ByVal encl As Double, ByVal bat As Double, _
            ByVal erSub As Double, ByVal supId As Double, ByVal outDir As String)

    StoreDoubleParameter "enclosure_en", encl
    StoreDoubleParameter "battery_mode", bat
    StoreDoubleParameter "er_fr4", erSub
    StoreDoubleParameter "superstrate_id", supId
    StoreDoubleParameter "h_superstrate", 2.00

    Rebuild
    Solver.Start

    ' Export 1-port S-parameters as 50-Ohm Touchstone (.s1p)
    With TOUCHSTONE
        .Reset
        .FileName outDir & "/" & caseTag
        .Impedance "50"
        .FrequencyRange "Full"
        .Renormalize "True"
        .UseARResults "False"
        .Write
    End With

    ' Export 866.5 MHz 3D Farfield Realized Gain & Efficiency summary
    SelectTreeItem "Farfields\farfield (f2_866p5MHz) [1]"
    With FarfieldPlot
        .Reset
        .Plottype "3D"
        .PlotMode "realized gain"
        .Plot
        .ASCIIExportAsSource outDir & "/farfield_866p5MHz_" & caseTag & ".txt"
    End With
End Sub

Sub Main()
    Dim outDir As String
    outDir = GetProjectPath("Project") & "\cst_exports"
    On Error Resume Next
    MkDir outDir
    On Error GoTo 0

    ' Run all 10 benchmark cases (Mode 1 = Full Front-End with 3D Elliptic Pi-Filter)
    StoreDoubleParameter "excitation_mode", 1

    RunCase "01_bare_pcb",          0, 0, 4.40, 0, outDir
    RunCase "02_dry_air",           1, 0, 4.40, 0, outDir
    RunCase "03_enclosed_lipo",     1, 1, 4.40, 0, outDir
    RunCase "04_fr4_low_4p2",       1, 0, 4.20, 0, outDir
    RunCase "05_fr4_high_4p6",      1, 0, 4.60, 0, outDir
    RunCase "06_oil_ptfe",          1, 0, 4.40, 1, outDir
    RunCase "07_glaze_ice",         1, 0, 4.40, 2, outDir
    RunCase "08_alumina_al2o3",     1, 0, 4.40, 3, outDir
    RunCase "09_ipa_debye",         1, 0, 4.40, 4, outDir
    RunCase "10_water_debye",       1, 0, 4.40, 5, outDir

    MsgBox "Completed all 10 ISAC Rev E.5 CST antenna & superstrate sweeps -> " & outDir, vbInformation
End Sub
