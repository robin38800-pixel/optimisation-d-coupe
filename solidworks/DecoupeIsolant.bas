Attribute VB_Name = "ModDecoupe"
Option Explicit

'==========================================================================
' DECOUPE ISOLANT - macro SolidWorks (2024)
'
' A lancer depuis une MISE EN PLAN qui contient la nomenclature des isolants :
'   1. lit la nomenclature (repere + quantite de chaque piece),
'   2. releve le contour de la plus grande face plane de chaque piece,
'   3. appelle DecoupeIsolant.exe qui repartit les pieces dans les plaques,
'   4. cree une nouvelle feuille "Plaques ..." avec les plaques et les pieces.
'
' Un journal detaille est ecrit dans  %TEMP%\DecoupeIsolant\journal.txt
' (a m'envoyer en cas de probleme).
'==========================================================================

' ------------------------- Reglages modifiables -------------------------
Const LARGEUR_PLAQUE As Double = 1500   ' mm
Const HAUTEUR_PLAQUE As Double = 1000   ' mm
Const MARGE_BORD As Double = 0          ' mm : distance mini piece / bord de plaque
Const TEMPS_CALCUL As Long = 30         ' secondes de recherche
Const ECART_PLAQUES As Double = 100     ' mm entre deux plaques sur la feuille
Const HAUTEUR_TEXTE As Double = 25      ' mm : hauteur des numeros de pieces
Const NB_POINTS_COURBE As Long = 24     ' points par arete courbe (arcs, cercles)
Const MODE_VUES As Boolean = True       ' True : vraies vues des pieces ; False : simples traits (esquisse)
Const PI As Double = 3.14159265358979

' --------------------- Constantes SolidWorks (liaison tardive) ----------
Const swDocPART As Long = 1
Const swDocASSEMBLY As Long = 2
Const swDocDRAWING As Long = 3
Const swOpenDocOptions_Silent As Long = 1
Const swDwgPapersUserDefined As Long = 12
Const swDwgTemplateNone As Long = 7

Const TITRE As String = "Decoupe isolant"

Dim swApp As Object
Dim cheminJournal As String
Dim swDessin As Object                 ' mise en plan active
Dim infosPieces As Object              ' repere -> (chemin, configuration, vue, axe u, axe v)

'==========================================================================
' Programme principal
'==========================================================================
Sub main()
    Dim swModel As Object
    Dim dossier As String, fEntree As String, fResultat As String, fDxf As String
    Dim exe As String, cmd As String, sh As Object
    Dim espacement As Double, epaisseur As Double
    Dim saisie As String, nbPieces As Long, code As Long

    On Error GoTo Erreur

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "Ouvrez d'abord la mise en plan contenant la nomenclature des isolants.", vbExclamation, TITRE
        Exit Sub
    End If
    If swModel.GetType <> swDocDRAWING Then
        MsgBox "Cette macro doit etre lancee depuis une mise en plan (avec sa nomenclature).", vbExclamation, TITRE
        Exit Sub
    End If

    Set swDessin = swModel
    dossier = Environ("TEMP") & "\DecoupeIsolant"
    If Dir(dossier, vbDirectory) = "" Then MkDir dossier
    OuvrirJournal dossier & "\journal.txt"
    Journal "Plan : " & swModel.GetPathName
    Journal "Version SolidWorks : " & swApp.RevisionNumber

    exe = TrouverExe()
    If exe = "" Then GoTo Fin

    saisie = InputBox("Espacement minimal entre deux pieces (mm) :", TITRE, GetSetting("DecoupeIsolant", "Config", "Espacement", "2"))
    If saisie = "" Then GoTo Fin
    espacement = LireNombre(saisie)
    SaveSetting "DecoupeIsolant", "Config", "Espacement", saisie

    saisie = InputBox("Epaisseur des isolants a decouper (mm)." & vbCrLf & _
                      "Laissez VIDE pour prendre toutes les pieces de la nomenclature.", TITRE, _
                      GetSetting("DecoupeIsolant", "Config", "Epaisseur", ""))
    epaisseur = 0
    If Trim$(saisie) <> "" Then epaisseur = LireNombre(saisie)
    SaveSetting "DecoupeIsolant", "Config", "Epaisseur", saisie

    fEntree = dossier & "\entree.txt"
    fResultat = dossier & "\resultat.txt"
    If swModel.GetPathName <> "" Then
        fDxf = Left$(swModel.GetPathName, InStrRev(swModel.GetPathName, ".") - 1) & "_plaques.dxf"
    Else
        fDxf = dossier & "\plaques.dxf"
    End If

    nbPieces = EcrireEchange(swModel, fEntree, epaisseur)
    If nbPieces = 0 Then
        MsgBox "Aucune piece exploitable n'a ete trouvee dans la nomenclature." & vbCrLf & _
               "Consultez le journal : " & dossier & "\journal.txt", vbExclamation, TITRE
        GoTo Fin
    End If

    If Dir(fResultat) <> "" Then Kill fResultat
    cmd = """" & exe & """ --echange """ & fEntree & """ --resultat-echange """ & fResultat & """ -o """ & fDxf & """" & _
          " --largeur " & Num(LARGEUR_PLAQUE) & " --hauteur " & Num(HAUTEUR_PLAQUE) & _
          " --espacement " & Num(espacement) & " --marge " & Num(MARGE_BORD) & " --temps " & TEMPS_CALCUL
    Journal "Commande : " & cmd

    If MsgBox(nbPieces & " pieces trouvees dans la nomenclature." & vbCrLf & vbCrLf & _
              "Le calcul dure environ " & TEMPS_CALCUL & " secondes. SolidWorks restera fige pendant ce temps." & vbCrLf & _
              "Lancer le calcul ?", vbOKCancel + vbQuestion, TITRE) = vbCancel Then GoTo Fin
    Set sh = CreateObject("WScript.Shell")
    code = sh.Run(cmd, 0, True)
    Journal "Code retour du calcul : " & code

    If Dir(fResultat) = "" Then
        MsgBox "Le programme de calcul n'a produit aucun resultat." & vbCrLf & _
               "Verifiez le chemin de DecoupeIsolant.exe. Journal : " & dossier & "\journal.txt", vbCritical, TITRE
        GoTo Fin
    End If

    DessinerResultat swModel, fResultat, fDxf

Fin:
    FermerJournal
    Exit Sub

Erreur:
    Journal "ERREUR " & Err.Number & " : " & Err.Description
    MsgBox "Erreur inattendue : " & Err.Description & vbCrLf & "Journal : " & Environ("TEMP") & "\DecoupeIsolant\journal.txt", vbCritical, TITRE
    Resume Fin
End Sub

'==========================================================================
' Etape 1 : nomenclature -> fichier d'echange
'==========================================================================
Private Function EcrireEchange(ByVal swModel As Object, chemin As String, epaisseur As Double) As Long
    Dim tables As Collection, configs As Collection
    Dim f As Integer, t As Long, total As Long
    Set tables = New Collection
    Set configs = New Collection
    ChercherNomenclatures swModel.FirstFeature, tables, configs
    Journal "Nomenclatures trouvees : " & tables.Count

    If tables.Count = 0 Then
        MsgBox "Aucune nomenclature (BOM) trouvee dans cette mise en plan.", vbExclamation, TITRE
        Exit Function
    End If

    Set infosPieces = CreateObject("Scripting.Dictionary")
    f = FreeFile
    Open chemin For Output As #f
    Print #f, "DECOUPE-ECHANGE 1"
    JournalAssemblage swModel
    For t = 1 To tables.Count
        total = total + LireTable(f, tables(t), ConfigsCandidates(swModel, CStr(configs(t))), epaisseur)
    Next t
    Print #f, "FIN"
    Close #f
    EcrireEchange = total
End Function

Private Sub ChercherNomenclatures(ByVal premier As Object, tables As Collection, configs As Collection)
    Dim feat As Object, fils As Object, spec As Object
    Dim v As Variant, i As Long, cfg As String
    Set feat = premier
    Do While Not feat Is Nothing
        If feat.GetTypeName2 = "BomFeat" Then
            Set spec = feat.GetSpecificFeature2
            cfg = ""
            On Error Resume Next
            cfg = spec.Configuration
            Err.Clear
            v = spec.GetTableAnnotations
            On Error GoTo 0
            If IsArray(v) Then
                For i = LBound(v) To UBound(v)
                    tables.Add v(i)
                    configs.Add cfg
                Next i
            End If
        End If
        Set fils = Nothing
        On Error Resume Next
        Set fils = feat.GetFirstSubFeature
        On Error GoTo 0
        If Not fils Is Nothing Then ChercherNomenclatures fils, tables, configs
        Set feat = feat.GetNextFeature
    Loop
End Sub

Private Function LireTable(f As Integer, ByVal tbl As Object, cfgs As Collection, epaisseur As Double) As Long
    Dim r As Long, c As Long, nbLignes As Long, nbCol As Long, colQte As Long
    Dim repere As String, refPiece As String, texte As String, ligneTxt As String
    Dim nbComp As Long, qte As Long, comps As Variant, comp As Object
    Dim n As Long, k As Long, cfgOk As String, trouve As Boolean, essais As String
    Dim colDes As Long, desig As String, chemin As String, cfgVue As String, repTxt As String

    nbLignes = tbl.RowCount
    nbCol = tbl.ColumnCount
    Journal "Table : " & nbLignes & " lignes, " & nbCol & " colonnes"

    ' contenu complet du tableau (diagnostic)
    For r = 0 To nbLignes - 1
        ligneTxt = ""
        For c = 0 To nbCol - 1
            ligneTxt = ligneTxt & Replace(tbl.Text(r, c), vbCrLf, " ") & " | "
        Next c
        Journal "  [" & r & "] " & ligneTxt
    Next r

    ' colonne "quantite" : repere dans la premiere ligne (en-tete)
    colQte = -1
    colDes = -1
    For c = 0 To nbCol - 1
        texte = UCase$(tbl.Text(0, c))
        If InStr(texte, "QT") > 0 Or InStr(texte, "QUANT") > 0 Then colQte = c
        If InStr(texte, "DESIGN") > 0 Then colDes = c
    Next c
    Journal "  colonne quantite : " & colQte & ", colonne designation : " & colDes

    cfgOk = ""
    trouve = False
    For r = 0 To nbLignes - 1
        repere = "": refPiece = "": nbComp = 0
        essais = ""

        ' configuration deja validee, sinon on essaie toutes les candidates
        For k = 1 To cfgs.Count
            Dim cfg As String
            If trouve Then cfg = cfgOk Else cfg = CStr(cfgs(k))
            repere = "": refPiece = "": nbComp = 0
            On Error Resume Next
            nbComp = tbl.GetComponentsCount2(r, cfg, repere, refPiece)
            If Err.Number <> 0 Then
                essais = essais & " ['" & cfg & "' -> erreur " & Err.Description & "]"
                Err.Clear
                nbComp = 0
            Else
                essais = essais & " ['" & cfg & "' -> " & nbComp & "]"
            End If
            On Error GoTo 0
            If nbComp > 0 Then
                trouve = True
                cfgOk = cfg
            End If
            If trouve Then Exit For
        Next k

        If nbComp > 0 Then
            qte = nbComp
            If colQte >= 0 Then
                texte = Trim$(tbl.Text(r, colQte))
                If IsNumeric(texte) Then
                    If CLng(Val(texte)) > 0 Then qte = CLng(Val(texte))
                End If
            End If
            Journal "  ligne " & r & " : repere '" & repere & "', piece '" & refPiece & "', quantite " & qte & _
                    " (composants " & nbComp & ", config '" & cfgOk & "')"

            comps = Empty
            On Error Resume Next
            comps = tbl.GetComponents2(r, cfgOk)
            If Err.Number <> 0 Then Journal "    GetComponents2 : " & Err.Description
            Err.Clear
            On Error GoTo 0
            If IsArray(comps) Then
                Set comp = comps(LBound(comps))
                If EcrirePiece(f, comp, repere, refPiece, qte, epaisseur) Then n = n + 1
            Else
                Journal "    composants illisibles pour cette ligne"
            End If
        ElseIf r > 0 Then
            Journal "  ligne " & r & " : aucun composant par l'API (essais :" & essais & ")"
            ' repli : retrouver la piece d'apres le texte de la ligne
            repTxt = Trim$(tbl.Text(r, 0))
            desig = ""
            If colDes >= 0 Then
                desig = tbl.Text(r, colDes)
            Else
                For c = 0 To nbCol - 1
                    desig = desig & " " & tbl.Text(r, c)
                Next c
            End If
            qte = 1
            If colQte >= 0 Then
                texte = Trim$(tbl.Text(r, colQte))
                If IsNumeric(texte) Then
                    If CLng(Val(texte)) > 0 Then qte = CLng(Val(texte))
                End If
            End If
            chemin = CheminPourLigne(desig, cfgVue)
            If chemin <> "" Then
                Journal "    piece retrouvee par son nom : " & chemin & " (configuration '" & cfgVue & "'), repere '" & repTxt & "', quantite " & qte
                If EcrirePieceParChemin(f, chemin, cfgVue, repTxt, desig, qte, epaisseur) Then n = n + 1
            Else
                Journal "    aucune piece trouvee pour '" & Trim$(desig) & "'"
            End If
        End If
    Next r
    LireTable = n
End Function

' Configurations a essayer : celle de la nomenclature, puis celles des vues du plan
Private Function ConfigsCandidates(ByVal swModel As Object, cfgBom As String) As Collection
    Dim col As Collection, v As Object, nom As String, i As Long
    Set col = New Collection
    AjouterUnique col, cfgBom
    On Error Resume Next
    Set v = swModel.GetFirstView
    Do While Not v Is Nothing And i < 500
        i = i + 1
        nom = ""
        nom = v.ReferencedConfiguration
        If Err.Number <> 0 Then Err.Clear
        If nom <> "" Then AjouterUnique col, nom
        Set v = v.GetNextView
        If Err.Number <> 0 Then
            Err.Clear
            Exit Do
        End If
    Loop
    On Error GoTo 0
    AjouterUnique col, ""
    Dim s As String
    For i = 1 To col.Count
        s = s & " '" & col(i) & "'"
    Next i
    Journal "  configurations candidates :" & s
    Set ConfigsCandidates = col
End Function

Private Sub AjouterUnique(col As Collection, s As String)
    On Error Resume Next
    col.Add s, "k_" & s
    Err.Clear
End Sub

' Diagnostic : toutes les vues du plan et le modele qu'elles referencent
Private Sub JournalAssemblage(ByVal swModel As Object)
    Dim v As Object, i As Long, nom As String, chemin As String, cfg As String
    On Error Resume Next
    Set v = swModel.GetFirstView
    Do While Not v Is Nothing And i < 500
        i = i + 1
        nom = "": chemin = "": cfg = ""
        nom = v.GetName2
        chemin = v.GetReferencedModelName
        cfg = v.ReferencedConfiguration
        Err.Clear
        Journal "Vue " & i & " : '" & nom & "' -> " & chemin & " [config '" & cfg & "']"
        Set v = v.GetNextView
        If Err.Number <> 0 Then
            Err.Clear
            Exit Do
        End If
    Loop
    If i = 0 Then Journal "Aucune vue lue dans le plan"
End Sub

'--------------------------------------------------------------------------
' Contour de la plus grande face plane d'une piece
'--------------------------------------------------------------------------
Private Function EcrirePiece(f As Integer, ByVal comp As Object, repere As String, refPiece As String, _
                             qte As Long, epaisseur As Double) As Boolean
    Dim modele As Object, chemin As String, cfgComp As String

    On Error GoTo Echec
    chemin = ""
    chemin = comp.GetPathName
    If LCase$(Right$(chemin, 7)) = ".sldasm" Then
        Journal "    sous-assemblage ignore : " & chemin
        Exit Function
    End If

    Set modele = comp.GetModelDoc2
    If modele Is Nothing Then Set modele = ModeleParChemin(chemin)
    If modele Is Nothing Then
        Journal "    modele introuvable : " & chemin
        Exit Function
    End If

    cfgComp = ""
    On Error Resume Next
    cfgComp = comp.ReferencedConfiguration
    On Error GoTo Echec
    EcrirePiece = EcrireModele(f, modele, chemin, cfgComp, repere, refPiece, qte, epaisseur)
    Exit Function

Echec:
    Journal "    ERREUR sur la piece '" & refPiece & "' : " & Err.Description
End Function

' Meme chose a partir du chemin d'un fichier de piece (quand la nomenclature ne donne pas les composants)
Private Function EcrirePieceParChemin(f As Integer, chemin As String, cfg As String, repere As String, _
                                      nom As String, qte As Long, epaisseur As Double) As Boolean
    Dim modele As Object
    On Error GoTo Echec
    Set modele = ModeleParChemin(chemin)
    If modele Is Nothing Then
        Journal "    modele impossible a ouvrir : " & chemin
        Exit Function
    End If
    EcrirePieceParChemin = EcrireModele(f, modele, chemin, cfg, repere, nom, qte, epaisseur)
    Exit Function

Echec:
    Journal "    ERREUR sur la piece '" & nom & "' : " & Err.Description
End Function

Private Function ModeleParChemin(chemin As String) As Object
    Dim m As Object, e As Long, w As Long
    Set m = Nothing
    On Error Resume Next
    Set m = swApp.GetOpenDocumentByName(chemin)
    Err.Clear
    On Error GoTo 0
    If m Is Nothing Then Set m = swApp.OpenDoc6(chemin, swDocPART, swOpenDocOptions_Silent, "", e, w)
    Set ModeleParChemin = m
End Function

' Ecrit le contour de la plus grande face plane d'un modele de piece
Private Function EcrireModele(f As Integer, ByVal modele As Object, chemin As String, cfgComp As String, _
                              repere As String, refPiece As String, qte As Long, epaisseur As Double) As Boolean
    Dim nom As String
    Dim face As Object, aire As Double, normale As Variant
    Dim lp As Object, loops As Variant, aretes As Variant
    Dim i As Long, k As Long, nbAretes As Long
    Dim ep As Double, ligne As String
    Dim cleVue As String, axesVue As Variant

    On Error GoTo Echec
    If modele.GetType <> swDocPART Then
        Journal "    ce n'est pas une piece : " & chemin
        Exit Function
    End If
    nom = refPiece
    If nom = "" Then nom = modele.GetTitle

    Set face = GrandeFacePlane(modele, aire, normale)
    If face Is Nothing Then
        Journal "    aucune face plane trouvee : " & nom
        Exit Function
    End If

    ep = Epaisseur_mm(modele, aire)
    Journal "    face la plus grande : " & Format$(aire * 1000000#, "0") & " mm2, epaisseur estimee " & Format$(ep, "0.0") & " mm"
    If epaisseur > 0 And ep > 0 Then
        If Abs(ep - epaisseur) > 0.6 Then
            Journal "    ignoree : epaisseur differente de " & epaisseur & " mm"
            Exit Function
        End If
    End If

    loops = face.GetLoops
    For i = LBound(loops) To UBound(loops)
        Set lp = loops(i)
        If lp.IsOuter Then
            aretes = lp.GetEdges
            Exit For
        End If
    Next i
    If Not IsArray(aretes) Then
        Journal "    contour exterieur introuvable : " & nom
        Exit Function
    End If

    cleVue = ChoisirVue(normale, axesVue)
    Print #f, "PIECE|" & Nettoyer(repere) & "|" & qte & "|" & Nettoyer(nom)
    Print #f, "NORMALE " & Num6(normale(0)) & " " & Num6(normale(1)) & " " & Num6(normale(2))
    If cleVue <> "" Then
        Print #f, "VUE " & cleVue
        Print #f, "BASE " & Num6(axesVue(0)) & " " & Num6(axesVue(1)) & " " & Num6(axesVue(2)) & " " & _
                            Num6(axesVue(3)) & " " & Num6(axesVue(4)) & " " & Num6(axesVue(5))
        infosPieces(repere) = Array(chemin, cfgComp, cleVue, axesVue(0), axesVue(1), axesVue(2), axesVue(3), axesVue(4), axesVue(5))
        Journal "    vue standard : " & cleVue & " (configuration '" & cfgComp & "')"
    Else
        Journal "    face non parallele a un plan principal : cette piece sera dessinee en traits"
    End If
    For k = LBound(aretes) To UBound(aretes)
        ligne = PointsArete(aretes(k))
        If ligne <> "" Then
            Print #f, "P " & ligne
            nbAretes = nbAretes + 1
        End If
    Next k
    Journal "    " & nbAretes & " aretes ecrites"
    EcrireModele = (nbAretes >= 3)
    Exit Function

Echec:
    Journal "    ERREUR sur la piece '" & refPiece & "' : " & Err.Description
End Function

'--------------------------------------------------------------------------
' Retrouve le fichier d'une piece d'apres le texte de la nomenclature
' (par exemple "N PLAN:CALORIFUGE ECF A1-A") : d'abord parmi les modeles
' references par les vues du plan, puis dans le dossier du plan.
'--------------------------------------------------------------------------
Private Function Normaliser(s As String) As String
    Dim r As String
    r = UCase$(s)
    r = Replace(r, " ", "")
    r = Replace(r, "_", "")
    r = Replace(r, "-", "")
    Normaliser = r
End Function

Private Function CheminPourLigne(designation As String, ByRef cfg As String) As String
    Dim cle As String, v As Object, chemin As String, nomFic As String
    Dim i As Long, dossier As String, trouve As String, chemDessin As String

    cle = designation
    If InStr(cle, ":") > 0 Then cle = Mid$(cle, InStr(cle, ":") + 1)
    cle = Trim$(cle)
    If cle = "" Then Exit Function
    cfg = ""

    ' 1) modeles references par les vues du plan
    On Error Resume Next
    Set v = swDessin.GetFirstView
    Do While Not v Is Nothing And i < 500
        i = i + 1
        chemin = ""
        chemin = v.GetReferencedModelName
        If Err.Number <> 0 Then Err.Clear
        If chemin <> "" Then
            nomFic = Mid$(chemin, InStrRev(chemin, "\") + 1)
            If InStr(Normaliser(nomFic), Normaliser(cle)) > 0 Then
                cfg = v.ReferencedConfiguration
                If Err.Number <> 0 Then Err.Clear
                CheminPourLigne = chemin
                Exit Function
            End If
        End If
        Set v = v.GetNextView
        If Err.Number <> 0 Then
            Err.Clear
            Exit Do
        End If
    Loop

    ' 2) fichiers du dossier du plan
    chemDessin = swDessin.GetPathName
    On Error GoTo 0
    If chemDessin <> "" Then
        dossier = Left$(chemDessin, InStrRev(chemDessin, "\"))
        trouve = Dir(dossier & "*" & cle & "*.SLDPRT")
        If trouve <> "" Then CheminPourLigne = dossier & trouve
    End If
End Function

Private Function GrandeFacePlane(ByVal modele As Object, ByRef aireMax As Double, ByRef normale As Variant) As Object
    Dim corps As Variant, faces As Variant, i As Long, j As Long
    Dim b As Object, fc As Object, a As Double, meilleure As Object

    corps = modele.GetBodies2(0, True)      ' 0 = corps volumiques, visibles
    If Not IsArray(corps) Then Exit Function
    For i = LBound(corps) To UBound(corps)
        Set b = corps(i)
        faces = b.GetFaces
        If IsArray(faces) Then
            For j = LBound(faces) To UBound(faces)
                Set fc = faces(j)
                If fc.GetSurface.IsPlane Then
                    a = fc.GetArea
                    If a > aireMax Then
                        aireMax = a
                        Set meilleure = fc
                    End If
                End If
            Next j
        End If
    Next i
    If Not meilleure Is Nothing Then normale = meilleure.Normal
    Set GrandeFacePlane = meilleure
End Function

' Epaisseur = volume / aire de la grande face (en mm) ; 0 si inconnue
Private Function Epaisseur_mm(ByVal modele As Object, aireFace As Double) As Double
    Dim mp As Object, vol As Double
    On Error Resume Next
    Set mp = modele.Extension.CreateMassProperty
    vol = mp.Volume
    If Err.Number = 0 And aireFace > 0 Then Epaisseur_mm = vol / aireFace * 1000#
    Err.Clear
End Function

' Points d'une arete (mm), "x y z x y z ..."
Private Function PointsArete(ByVal arete As Object) As String
    Dim crv As Object, v1 As Object, v2 As Object
    Dim p1 As Variant, p2 As Variant, prm As Variant, p As Variant
    Dim t0 As Double, t1 As Double, i As Long, s As String
    Dim ligne As Boolean

    On Error GoTo Echec
    Set crv = arete.GetCurve
    Set v1 = arete.GetStartVertex
    Set v2 = arete.GetEndVertex
    ligne = crv.IsLine
    If ligne And Not v1 Is Nothing And Not v2 Is Nothing Then
        p1 = v1.GetPoint
        p2 = v2.GetPoint
        PointsArete = Pt(p1) & " " & Pt(p2)
        Exit Function
    End If

    prm = arete.GetCurveParams2
    t0 = prm(6)
    t1 = prm(7)
    For i = 0 To NB_POINTS_COURBE
        p = crv.Evaluate2(t0 + (t1 - t0) * i / NB_POINTS_COURBE, 0)
        If i > 0 Then s = s & " "
        s = s & Pt(p)
    Next i
    PointsArete = s
    Exit Function

Echec:
    ' dernier recours : corde entre les deux sommets
    Journal "    arete courbe non echantillonnee (" & Err.Description & ") : corde utilisee"
    Err.Clear
    On Error Resume Next
    p1 = v1.GetPoint
    p2 = v2.GetPoint
    If Err.Number = 0 Then PointsArete = Pt(p1) & " " & Pt(p2)
End Function

'==========================================================================
' Etape 3 : resultat -> nouvelle feuille de mise en plan
'==========================================================================
Private Sub DessinerResultat(ByVal swModel As Object, fResultat As String, fDxf As String)
    Dim lignes As Collection, l As String, f As Integer
    Dim nbPlaques As Long, larg As Double, haut As Double
    Dim t() As String

    Set lignes = New Collection
    f = FreeFile
    Open fResultat For Input As #f
    Do While Not EOF(f)
        Line Input #f, l
        If Trim$(l) <> "" Then lignes.Add l
    Loop
    Close #f

    If lignes.Count < 2 Then
        MsgBox "Le fichier de resultat est vide ou incomplet : " & fResultat, vbCritical, TITRE
        Exit Sub
    End If
    If Left$(lignes(2), 6) = "ERREUR" Then
        Journal "Le calcul a renvoye : " & lignes(2)
        MsgBox "Le calcul a echoue :" & vbCrLf & Mid$(lignes(2), 8), vbCritical, TITRE
        Exit Sub
    End If
    If Trim$(lignes(1)) <> "DECOUPE-RESULTAT 2" Then
        Journal "Format de resultat inattendu : " & lignes(1)
        MsgBox "DecoupeIsolant.exe est trop ancien pour cette macro." & vbCrLf & _
               "Telechargez la derniere version de l'application et remplacez l'ancien fichier.", vbCritical, TITRE
        Exit Sub
    End If

    t = Split(lignes(2), " ")        ' PLAQUES n largeur hauteur
    nbPlaques = CLng(Val(t(1)))
    larg = Val(t(2))
    haut = Val(t(3))

    Dim nomFeuille As String, ok As Boolean
    nomFeuille = "Plaques " & Format$(Now, "hhnnss")
    ok = swModel.NewSheet3(nomFeuille, swDwgPapersUserDefined, swDwgTemplateNone, 1#, 1#, True, "", _
                           (nbPlaques * (larg + ECART_PLAQUES) + ECART_PLAQUES) / 1000#, (haut + 4# * ECART_PLAQUES) / 1000#, "")
    Journal "Creation de la feuille '" & nomFeuille & "' : " & ok
    If Not ok Then
        MsgBox "Impossible de creer la feuille. Le DXF du resultat est disponible :" & vbCrLf & fDxf, vbExclamation, TITRE
        Exit Sub
    End If
    swModel.ActivateSheet nomFeuille

    ' ---- passe 1 : les vues (aucune esquisse ne doit etre ouverte) ----
    Dim i As Long, plaque As Long, ox As Double, oy As Double, taux As String
    Dim q() As String, rep() As String, coord() As String, tr() As String
    Dim n As Long, k As Long, x As Double, y As Double
    Dim xmin As Double, ymin As Double, xmax As Double, ymax As Double
    Dim place As Boolean, nbVues As Long, nbTraits As Long, msg As String
    Dim plaques As Collection, poses As Collection
    Set plaques = New Collection
    Set poses = New Collection

    oy = ECART_PLAQUES
    For i = 3 To lignes.Count
        l = lignes(i)
        If Left$(l, 7) = "PLAQUE " Then
            q = Split(l, " ")
            plaque = CLng(Val(q(1)))
            taux = q(2)
            ox = ECART_PLAQUES + (plaque - 1) * (larg + ECART_PLAQUES)
            plaques.Add Array(ox, oy, "Plaque " & plaque & " - remplissage " & taux & " %")
        ElseIf Left$(l, 5) = "POSE " Then
            rep = Split(Mid$(l, 6), "|")     ' repere | etiquette | nom | angle tx ty | n x y x y ...
            tr = Split(rep(3), " ")
            coord = Split(rep(4), " ")
            n = CLng(Val(coord(0)))
            xmin = 1E+30: ymin = 1E+30: xmax = -1E+30: ymax = -1E+30
            For k = 0 To n - 1
                x = Val(coord(1 + 2 * k)): y = Val(coord(2 + 2 * k))
                If x < xmin Then xmin = x
                If x > xmax Then xmax = x
                If y < ymin Then ymin = y
                If y > ymax Then ymax = y
            Next k
            place = False
            If MODE_VUES Then
                place = PlacerVue(swModel, rep(0), Val(tr(0)), ox + (xmin + xmax) / 2, oy + (ymin + ymax) / 2, xmax - xmin, ymax - ymin)
            End If
            If place Then nbVues = nbVues + 1 Else nbTraits = nbTraits + 1
            poses.Add Array(rep(1), ox, oy, rep(4), place, (xmin + xmax) / 2, (ymin + ymax) / 2)
        End If
    Next i

    ' ---- passe 2 : cadres des plaques, pieces en traits (si pas de vue) et numeros ----
    Dim sm As Object, p As Variant, c As Variant
    Set sm = swModel.SketchManager
    sm.InsertSketch True
    sm.AddToDB = True
    For Each p In plaques
        DessinerRectangle sm, CDbl(p(0)), CDbl(p(1)), CDbl(p(0)) + larg, CDbl(p(1)) + haut
    Next p
    For Each p In poses
        If Not p(4) Then
            coord = Split(p(3), " ")
            n = CLng(Val(coord(0)))
            For k = 0 To n - 1
                TracerSegment sm, CDbl(p(1)) + Val(coord(1 + 2 * k)), CDbl(p(2)) + Val(coord(2 + 2 * k)), _
                              CDbl(p(1)) + Val(coord(1 + 2 * ((k + 1) Mod n))), CDbl(p(2)) + Val(coord(2 + 2 * ((k + 1) Mod n)))
            Next k
        End If
    Next p
    sm.AddToDB = False
    sm.InsertSketch True
    swModel.ClearSelection2 True

    For Each p In plaques
        PoserTexte swModel, CStr(p(2)), CDbl(p(0)), CDbl(p(1)) + haut + 40
    Next p
    For Each p In poses
        PoserTexte swModel, CStr(p(0)), CDbl(p(1)) + CDbl(p(5)), CDbl(p(2)) + CDbl(p(6))
    Next p

    swModel.ViewZoomtofit2
    Journal nbVues & " vues et " & nbTraits & " pieces en traits sur " & nbPlaques & " plaque(s)"
    msg = (nbVues + nbTraits) & " pieces reparties sur " & nbPlaques & " plaque(s)." & vbCrLf & _
          nbVues & " en vues, " & nbTraits & " en traits." & vbCrLf & _
          "Feuille creee : " & nomFeuille & vbCrLf & "DXF : " & fDxf
    MsgBox msg, vbInformation, TITRE
End Sub

'--------------------------------------------------------------------------
' Vue standard dont la direction de regard est la normale de la face
' Renvoie "" si la face n'est pas parallele a un plan principal.
' base = axes 2D de la vue (x puis y) exprimes dans le repere de la piece.
'--------------------------------------------------------------------------
Private Function ChoisirVue(normale As Variant, ByRef axesVue As Variant) As String
    Const SEUIL As Double = 0.9995
    Dim nx As Double, ny As Double, nz As Double, lg As Double
    nx = CDbl(normale(0)): ny = CDbl(normale(1)): nz = CDbl(normale(2))
    lg = Sqr(nx * nx + ny * ny + nz * nz)
    If lg < 0.000001 Then Exit Function
    nx = nx / lg: ny = ny / lg: nz = nz / lg

    If nz > SEUIL Then
        ChoisirVue = "Face":    axesVue = Array(1#, 0#, 0#, 0#, 1#, 0#)
    ElseIf nz < -SEUIL Then
        ChoisirVue = "Arriere": axesVue = Array(-1#, 0#, 0#, 0#, 1#, 0#)
    ElseIf ny > SEUIL Then
        ChoisirVue = "Dessus":  axesVue = Array(1#, 0#, 0#, 0#, 0#, -1#)
    ElseIf ny < -SEUIL Then
        ChoisirVue = "Dessous": axesVue = Array(1#, 0#, 0#, 0#, 0#, 1#)
    ElseIf nx > SEUIL Then
        ChoisirVue = "Droite":  axesVue = Array(0#, 0#, -1#, 0#, 1#, 0#)
    ElseIf nx < -SEUIL Then
        ChoisirVue = "Gauche":  axesVue = Array(0#, 0#, 1#, 0#, 1#, 0#)
    End If
End Function

' Noms possibles de la vue (francais puis anglais) selon la langue de SolidWorks
Private Function NomsVue(cle As String) As Variant
    Select Case cle
        Case "Face":    NomsVue = Array("*Face", "*Front")
        Case "Arriere": NomsVue = Array("*Arrière", "*Arriere", "*Back")
        Case "Dessus":  NomsVue = Array("*Dessus", "*Top")
        Case "Dessous": NomsVue = Array("*Dessous", "*Bottom")
        Case "Gauche":  NomsVue = Array("*Gauche", "*Left")
        Case "Droite":  NomsVue = Array("*Droite", "*Right")
        Case Else:      NomsVue = Array("*Face")
    End Select
End Function

Private Function Atan2(y As Double, x As Double) As Double
    If x > 0 Then
        Atan2 = Atn(y / x)
    ElseIf x < 0 Then
        If y >= 0 Then
            Atan2 = Atn(y / x) + PI
        Else
            Atan2 = Atn(y / x) - PI
        End If
    ElseIf y > 0 Then
        Atan2 = PI / 2
    ElseIf y < 0 Then
        Atan2 = -PI / 2
    End If
End Function

' Ecart d'angle ramene entre -PI et PI
Private Function EcartAngle(ByVal a As Double) As Double
    Do While a > PI
        a = a - 2 * PI
    Loop
    Do While a < -PI
        a = a + 2 * PI
    Loop
    EcartAngle = a
End Function

' Angle (dans le plan de la feuille) d'un vecteur du modele, apres transformation de la vue
Private Function AngleVecteur(ByVal v As Object, ux As Double, uy As Double, uz As Double, ByRef longueur As Double) As Double
    Dim mu As Object, xf As Object, p0 As Object, p1 As Object, a As Variant, b As Variant
    Dim dx As Double, dy As Double
    Set mu = swApp.GetMathUtility
    Set xf = v.ModelToViewTransform
    Set p0 = mu.CreatePoint(Array(0#, 0#, 0#))
    Set p1 = mu.CreatePoint(Array(ux * 0.1, uy * 0.1, uz * 0.1))
    a = p0.MultiplyTransform(xf).ArrayData
    b = p1.MultiplyTransform(xf).ArrayData
    dx = CDbl(b(0)) - CDbl(a(0))
    dy = CDbl(b(1)) - CDbl(a(1))
    longueur = Sqr(dx * dx + dy * dy)
    AngleVecteur = Atan2(dy, dx)
End Function

'--------------------------------------------------------------------------
' Cree la vue du modele, la tourne de thetaDeg et centre sa boite sur (cxMm, cyMm)
' Renvoie False si la vue n'a pas pu etre creee correctement (la piece est alors tracee en traits).
'--------------------------------------------------------------------------
Private Function PlacerVue(ByVal swModel As Object, repere As String, thetaDeg As Double, _
                           cxMm As Double, cyMm As Double, wMm As Double, hMm As Double) As Boolean
    Dim info As Variant, noms As Variant, i As Long, v As Object
    Dim th As Double, a0 As Double, aV0 As Double, a1 As Double, lg As Double
    Dim ol As Variant, pos As Variant, dx As Double, dy As Double, nomVue As String

    If infosPieces Is Nothing Then Exit Function
    If Not infosPieces.Exists(repere) Then
        Journal "  repere " & repere & " : pas d'information de vue, trace en traits"
        Exit Function
    End If
    info = infosPieces(repere)
    noms = NomsVue(CStr(info(2)))

    For i = LBound(noms) To UBound(noms)
        Set v = Nothing
        On Error Resume Next
        Set v = swModel.CreateDrawViewFromModelView3(CStr(info(0)), CStr(noms(i)), cxMm / 1000#, cyMm / 1000#, 0#)
        If Err.Number <> 0 Then
            Journal "  vue '" & noms(i) & "' : " & Err.Description
            Err.Clear
        End If
        On Error GoTo 0
        If Not v Is Nothing Then
            Journal "  repere " & repere & " : vue '" & noms(i) & "' creee"
            Exit For
        End If
    Next i
    If v Is Nothing Then
        Journal "  repere " & repere & " : creation de la vue impossible, trace en traits"
        Exit Function
    End If

    On Error GoTo Echec

    On Error Resume Next                    ' configuration de la piece dans l'assemblage (facultatif)
    v.ReferencedConfiguration = CStr(info(1))
    Err.Clear
    On Error GoTo Echec

    ' 1) la vue doit montrer le repere de la piece comme prevu : axe u vers la droite, axe v vers le haut
    a0 = AngleVecteur(v, CDbl(info(3)), CDbl(info(4)), CDbl(info(5)), lg)
    aV0 = AngleVecteur(v, CDbl(info(6)), CDbl(info(7)), CDbl(info(8)), lg)
    If Abs(EcartAngle(a0)) > 0.02 Or Abs(EcartAngle(aV0 - a0 - PI / 2)) > 0.02 Then
        Journal "  repere " & repere & " : orientation de la vue differente de celle prevue (u " & Format$(a0, "0.000") & _
                " rad, v " & Format$(aV0, "0.000") & " rad) : vue supprimee, trace en traits"
        SupprimerVue swModel, v
        Exit Function
    End If

    ' 2) rotation (le sens est verifie sur l'axe u de la piece)
    th = thetaDeg * PI / 180#
    If Abs(th) > 0.0001 Then
        v.Angle = th
        a1 = AngleVecteur(v, CDbl(info(3)), CDbl(info(4)), CDbl(info(5)), lg)
        If Abs(EcartAngle(a1 - a0 - th)) > 0.02 Then
            v.Angle = -th
            a1 = AngleVecteur(v, CDbl(info(3)), CDbl(info(4)), CDbl(info(5)), lg)
            Journal "  repere " & repere & " : sens de rotation inverse (ecart " & Format$(EcartAngle(a1 - a0 - th), "0.000") & ")"
        End If
    End If

    ' 3) centrage : la boite de la vue doit etre centree sur celle de la piece posee
    ol = v.GetOutline
    Journal "    boite de la vue : " & Format$((ol(2) - ol(0)) * 1000#, "0.0") & " x " & Format$((ol(3) - ol(1)) * 1000#, "0.0") & _
            " mm (attendu " & Format$(wMm, "0.0") & " x " & Format$(hMm, "0.0") & ")"
    dx = cxMm / 1000# - (CDbl(ol(0)) + CDbl(ol(2))) / 2#
    dy = cyMm / 1000# - (CDbl(ol(1)) + CDbl(ol(3))) / 2#
    pos = v.Position
    v.Position = Array(CDbl(pos(0)) + dx, CDbl(pos(1)) + dy)
    ol = v.GetOutline
    Journal "    ecart de centrage apres deplacement : " & Format$((cxMm / 1000# - (CDbl(ol(0)) + CDbl(ol(2))) / 2#) * 1000#, "0.00") & _
            " ; " & Format$((cyMm / 1000# - (CDbl(ol(1)) + CDbl(ol(3))) / 2#) * 1000#, "0.00") & " mm"
    PlacerVue = True
    Exit Function

Echec:
    Journal "  repere " & repere & " : ERREUR pendant le placement de la vue (" & Err.Description & ") : vue supprimee, trace en traits"
    Err.Clear
    On Error Resume Next
    SupprimerVue swModel, v
End Function

Private Sub SupprimerVue(ByVal swModel As Object, ByVal v As Object)
    Dim nom As String
    On Error Resume Next
    nom = v.GetName2
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 nom, "DRAWINGVIEW", 0#, 0#, 0#, False, 0, Nothing, 0
    swModel.EditDelete
    swModel.ClearSelection2 True
End Sub

' Trace un segment (coordonnees en mm, repere de la feuille)
Private Sub TracerSegment(ByVal sm As Object, x1 As Double, y1 As Double, x2 As Double, y2 As Double)
    Dim seg As Object
    Set seg = sm.CreateLine(x1 / 1000#, y1 / 1000#, 0#, x2 / 1000#, y2 / 1000#, 0#)
End Sub

Private Sub DessinerRectangle(ByVal sm As Object, x1 As Double, y1 As Double, x2 As Double, y2 As Double)
    TracerSegment sm, x1, y1, x2, y1
    TracerSegment sm, x2, y1, x2, y2
    TracerSegment sm, x2, y2, x1, y2
    TracerSegment sm, x1, y2, x1, y1
End Sub

Private Sub PoserTexte(ByVal swModel As Object, texte As String, x As Double, y As Double)
    Dim note As Object, ann As Object, tf As Object
    On Error GoTo Echec
    ' sans selection, la note ne s'accroche a rien (pas de ligne de repere)
    swModel.ClearSelection2 True
    Set note = swModel.InsertNote(texte)
    Set ann = note.GetAnnotation
    ann.SetPosition2 x / 1000#, y / 1000#, 0#
    On Error Resume Next                    ' la taille du texte est facultative
    Set tf = ann.GetTextFormat(0)
    tf.CharHeight = HAUTEUR_TEXTE / 1000#
    ann.SetTextFormat 0, False, tf
    Exit Sub
Echec:
    Journal "Texte non pose (" & texte & ") : " & Err.Description
End Sub

'==========================================================================
' Utilitaires
'==========================================================================
Private Function TrouverExe() As String
    Dim p As String, dossierMacro As String

    ' 1) chemin memorise lors d'un precedent lancement
    p = GetSetting("DecoupeIsolant", "Config", "Exe", "")
    If p <> "" Then
        If Dir(p) = "" Then p = ""
    End If

    ' 2) a cote du fichier .swp de la macro
    If p = "" Then
        dossierMacro = ""
        On Error Resume Next
        dossierMacro = swApp.GetCurrentMacroPathName
        On Error GoTo 0
        If dossierMacro <> "" Then
            dossierMacro = Left$(dossierMacro, InStrRev(dossierMacro, "\"))
            If Dir(dossierMacro & "DecoupeIsolant.exe") <> "" Then p = dossierMacro & "DecoupeIsolant.exe"
        End If
    End If

    ' 3) demande a l'utilisateur
    If p = "" Then
        p = InputBox("DecoupeIsolant.exe est introuvable." & vbCrLf & _
                     "Saisissez son chemin complet (vous pouvez le coller avec ses guillemets) :", TITRE, _
                     "C:\DecoupeIsolant\DecoupeIsolant.exe")
        p = Trim$(Replace(p, """", ""))
        If p = "" Then Exit Function
        If Dir(p) = "" Then
            MsgBox "Fichier introuvable : " & p & vbCrLf & vbCrLf & _
                   "Astuce : dans l'Explorateur, clic droit sur le fichier > Copier en tant que chemin d'acces.", vbCritical, TITRE
            Exit Function
        End If
    End If

    SaveSetting "DecoupeIsolant", "Config", "Exe", p
    Journal "Programme de calcul : " & p
    TrouverExe = p
End Function

' Nombres ecrits avec un point decimal, quelle que soit la langue de Windows
Private Function Num(x As Double) As String
    Num = Replace(Format$(x, "0.000"), ",", ".")
End Function

Private Function Num6(x As Variant) As String
    Num6 = Replace(Format$(CDbl(x), "0.000000"), ",", ".")
End Function

Private Function Pt(p As Variant) As String       ' point SolidWorks (m) -> "x y z" en mm
    Pt = Num(CDbl(p(0)) * 1000#) & " " & Num(CDbl(p(1)) * 1000#) & " " & Num(CDbl(p(2)) * 1000#)
End Function

Private Function LireNombre(s As String) As Double
    LireNombre = Val(Replace(s, ",", "."))
End Function

Private Function Nettoyer(s As String) As String
    Nettoyer = Replace(Replace(Replace(s, "|", "/"), vbCr, " "), vbLf, " ")
End Function

Private Sub OuvrirJournal(chemin As String)
    Dim n As Integer
    cheminJournal = chemin
    n = FreeFile
    Open cheminJournal For Output As #n
    Close #n
    Journal "=== " & TITRE & " - " & Format$(Now, "dd/mm/yyyy hh:nn:ss") & " ==="
End Sub

' Chaque ligne est ecrite et le fichier referme aussitot : le journal est lisible meme pendant un message
Private Sub Journal(s As String)
    Dim n As Integer
    If cheminJournal = "" Then Exit Sub
    On Error Resume Next
    n = FreeFile
    Open cheminJournal For Append As #n
    Print #n, s
    Close #n
End Sub

Private Sub FermerJournal()
    ' rien a faire : le journal est ferme apres chaque ligne
End Sub
