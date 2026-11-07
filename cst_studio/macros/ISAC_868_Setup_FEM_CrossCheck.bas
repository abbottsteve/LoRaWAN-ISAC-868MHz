' =============================================================================
' ISAC_868_Setup_FEM_CrossCheck.bas
' Configures CST Studio Frequency-Domain (Tetrahedral FEM) Solver @ 730-940 MHz
' with Curved Elements (Order 2) & Adaptive Mesh Refinement at 866.5 MHz
' to independently cross-check the Time-Domain Hexahedral FIT results.
' =============================================================================

Option Explicit

Sub Main()
    Dim sCmd As String

    StoreDoubleParameter "f_min", 0.73
    StoreDoubleParameter "f_max", 0.94

    sCmd = ""
    sCmd = sCmd & "Mesh.MeshType ""Tetrahedral""" & vbLf
    sCmd = sCmd & "With FDSolver" & vbLf
    sCmd = sCmd & "    .Reset" & vbLf
    sCmd = sCmd & "    .SetMethod ""Tetrahedral"", ""General purpose""" & vbLf
    sCmd = sCmd & "    .OrderTet ""Second""" & vbLf
    sCmd = sCmd & "    .OrderSrf ""First""" & vbLf
    sCmd = sCmd & "    .Stimulation ""1"", ""1""" & vbLf
    sCmd = sCmd & "    .ResetExcitationList" & vbLf
    sCmd = sCmd & "    .AutoNormImpedance ""False""" & vbLf
    sCmd = sCmd & "    .NormingImpedance ""50.0""" & vbLf
    sCmd = sCmd & "    .MeshAdaptionTet ""True""" & vbLf
    sCmd = sCmd & "    .SetAdaptionStrategy ""Energy""" & vbLf
    sCmd = sCmd & "    .AdaptionMinPasses ""3""" & vbLf
    sCmd = sCmd & "    .AdaptionMaxPasses ""8""" & vbLf
    sCmd = sCmd & "    .AdaptionAccuracy ""0.005""" & vbLf
    sCmd = sCmd & "    .AddSingleFrequencyAdaption ""0.8665"", ""True""" & vbLf
    sCmd = sCmd & "    .SweepErrorThreshold ""True"", ""0.002""" & vbLf
    sCmd = sCmd & "    .MaxNumberOfSamples ""1001""" & vbLf
    sCmd = sCmd & "End With" & vbLf
    AddToHistory "configure Tetrahedral FEM cross-check solver", sCmd

    Rebuild
    ' Uncomment FDSolver.Start below to launch immediately upon macro import:
    ' FDSolver.Start
End Sub
