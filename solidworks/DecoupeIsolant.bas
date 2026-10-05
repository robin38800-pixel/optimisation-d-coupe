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

' --------------------- Constantes SolidWorks (liaison tardive) ----------
Const swDocPART As Long = 1
Const swDocASSEMBLY As Long = 2
Const swDocDRAWING As Long = 3
Const swOpenDocOptions_Silent As Long = 1
Const swDwgPapersUserDefined As Long = 12
Const swDwgTemplateNone As Long = 7

Const TITRE As String = "Decoupe isolant"

Dim swApp As Object
Dim numLog As Integer
Dim logOuvert As Boolean

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
Private Function EcrireEchange(swModel As Object, chemin As String, epaisseur As Double) As Long
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

    f = FreeFile
    Open chemin For Output As #f
    Print #f, "DECOUPE-ECHANGE 1"
    For t = 1 To tables.Count
        total = total + LireTable(f, tables(t), CStr(configs(t)), epaisseur)
    Next t
    Print #f, "FIN"
    Close #f
    EcrireEchange = total
End Function

Private Sub ChercherNomenclatures(premier As Object, tables As Collection, configs As Collection)
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

Private Function LireTable(f As Integer, tbl As Object, cfg As String, epaisseur As Double) As Long
    Dim r As Long, c As Long, nbLignes As Long, nbCol As Long, colQte As Long
    Dim repere As String, refPiece As String, texte As String
    Dim nbComp As Long, qte As Long, comps As Variant, comp As Object
    Dim n As Long

    nbLignes = tbl.RowCount
    nbCol = tbl.ColumnCount
    Journal "Table : " & nbLignes & " lignes, " & nbCol & " colonnes, configuration '" & cfg & "'"

    ' colonne "quantite" : repere dans la premiere ligne (en-tete)
    colQte = -1
    For c = 0 To nbCol - 1
        texte = UCase$(tbl.Text(0, c))
        Journal "  en-tete col " & c & " : " & texte
        If InStr(texte, "QT") > 0 Or InStr(texte, "QUANT") > 0 Then colQte = c
    Next c
    Journal "  colonne quantite : " & colQte

    For r = 0 To nbLignes - 1
        repere = "": refPiece = "": nbComp = 0
        On Error Resume Next
        nbComp = tbl.GetComponentsCount2(r, cfg, repere, refPiece)
        If Err.Number <> 0 Then
            Journal "  ligne " & r & " : GetComponentsCount2 a echoue (" & Err.Description & ")"
            Err.Clear
            nbComp = 0
        End If
        On Error GoTo 0

        If nbComp > 0 Then
            qte = nbComp
            If colQte >= 0 Then
                texte = Trim$(tbl.Text(r, colQte))
                If IsNumeric(texte) Then
                    If CLng(Val(texte)) > 0 Then qte = CLng(Val(texte))
                End If
            End If
            Journal "  ligne " & r & " : repere '" & repere & "', piece '" & refPiece & "', quantite " & qte & " (composants " & nbComp & ")"

            comps = Empty
            On Error Resume Next
            comps = tbl.GetComponents2(r, cfg)
            On Error GoTo 0
            If IsArray(comps) Then
                Set comp = comps(LBound(comps))
                If EcrirePiece(f, comp, repere, refPiece, qte, epaisseur) Then n = n + 1
            Else
                Journal "    composants illisibles pour cette ligne"
            End If
        End If
    Next r
    LireTable = n
End Function

'--------------------------------------------------------------------------
' Contour de la plus grande face plane d'une piece
'--------------------------------------------------------------------------
Private Function EcrirePiece(f As Integer, comp As Object, repere As String, refPiece As String, _
                             qte As Long, epaisseur As Double) As Boolean
    Dim modele As Object, chemin As String, nom As String
    Dim face As Object, aire As Double, normale As Variant
    Dim lp As Object, loops As Variant, aretes As Variant
    Dim i As Long, k As Long, nbAretes As Long
    Dim ep As Double, ligne As String

    On Error GoTo Echec

    chemin = ""
    chemin = comp.GetPathName
    If LCase$(Right$(chemin, 7)) = ".sldasm" Then
        Journal "    sous-assemblage ignore : " & chemin
        Exit Function
    End If

    Set modele = comp.GetModelDoc2
    If modele Is Nothing Then
        Dim e As Long, w As Long
        Set modele = swApp.OpenDoc6(chemin, swDocPART, swOpenDocOptions_Silent, "", e, w)
    End If
    If modele Is Nothing Then
        Journal "    modele introuvable : " & chemin
        Exit Function
    End If
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

    Print #f, "PIECE|" & Nettoyer(repere) & "|" & qte & "|" & Nettoyer(nom)
    Print #f, "NORMALE " & Num6(normale(0)) & " " & Num6(normale(1)) & " " & Num6(normale(2))
    For k = LBound(aretes) To UBound(aretes)
        ligne = PointsArete(aretes(k))
        If ligne <> "" Then
            Print #f, "P " & ligne
            nbAretes = nbAretes + 1
        End If
    Next k
    Journal "    " & nbAretes & " aretes ecrites"
    EcrirePiece = (nbAretes >= 3)
    Exit Function

Echec:
    Journal "    ERREUR sur la piece '" & refPiece & "' : " & Err.Description
End Function

Private Function GrandeFacePlane(modele As Object, ByRef aireMax As Double, ByRef normale As Variant) As Object
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
Private Function Epaisseur_mm(modele As Object, aireFace As Double) As Double
    Dim mp As Object, vol As Double
    On Error Resume Next
    Set mp = modele.Extension.CreateMassProperty
    vol = mp.Volume
    If Err.Number = 0 And aireFace > 0 Then Epaisseur_mm = vol / aireFace * 1000#
    Err.Clear
End Function

' Points d'une arete (mm), "x y z x y z ..."
Private Function PointsArete(arete As Object) As String
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
Private Sub DessinerResultat(swModel As Object, fResultat As String, fDxf As String)
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

    Dim sm As Object
    Set sm = swModel.SketchManager
    sm.InsertSketch True
    sm.AddToDB = True

    Dim i As Long, plaque As Long, ox As Double, oy As Double, taux As String
    Dim q() As String, rep() As String, coord() As String, n As Long, k As Long
    Dim x1 As Double, y1 As Double, x2 As Double, y2 As Double, nbPoses As Long
    Dim textes As Collection
    Set textes = New Collection

    oy = ECART_PLAQUES
    For i = 3 To lignes.Count
        l = lignes(i)
        If Left$(l, 7) = "PLAQUE " Then
            q = Split(l, " ")
            plaque = CLng(Val(q(1)))
            taux = q(2)
            ox = ECART_PLAQUES + (plaque - 1) * (larg + ECART_PLAQUES)
            DessinerRectangle sm, ox, oy, ox + larg, oy + haut
            textes.Add Array("Plaque " & plaque & " - remplissage " & taux & " %", ox, oy + haut + 40)
        ElseIf Left$(l, 5) = "POSE " Then
            rep = Split(Mid$(l, 6), "|")            ' repere | etiquette | nom | n x y x y ...
            coord = Split(rep(3), " ")
            n = CLng(Val(coord(0)))
            Dim cx As Double, cy As Double
            cx = 0: cy = 0
            For k = 0 To n - 1
                x1 = Val(coord(1 + 2 * k)): y1 = Val(coord(2 + 2 * k))
                x2 = Val(coord(1 + 2 * ((k + 1) Mod n))): y2 = Val(coord(2 + 2 * ((k + 1) Mod n)))
                Ligne sm, ox + x1, oy + y1, ox + x2, oy + y2
                cx = cx + x1: cy = cy + y1
            Next k
            textes.Add Array(rep(1), ox + cx / n, oy + cy / n)
            nbPoses = nbPoses + 1
        End If
    Next i

    sm.AddToDB = False
    sm.InsertSketch True

    Dim tx As Variant
    For Each tx In textes
        PoserTexte swModel, CStr(tx(0)), CDbl(tx(1)), CDbl(tx(2))
    Next tx

    swModel.ViewZoomtofit2
    Journal nbPoses & " pieces dessinees sur " & nbPlaques & " plaque(s)"
    MsgBox nbPoses & " pieces reparties sur " & nbPlaques & " plaque(s)." & vbCrLf & _
           "Feuille creee : " & nomFeuille & vbCrLf & "DXF : " & fDxf, vbInformation, TITRE
End Sub

' Trace un segment (coordonnees en mm, repere de la feuille)
Private Sub Ligne(sm As Object, x1 As Double, y1 As Double, x2 As Double, y2 As Double)
    Dim seg As Object
    Set seg = sm.CreateLine(x1 / 1000#, y1 / 1000#, 0#, x2 / 1000#, y2 / 1000#, 0#)
End Sub

Private Sub DessinerRectangle(sm As Object, x1 As Double, y1 As Double, x2 As Double, y2 As Double)
    Ligne sm, x1, y1, x2, y1
    Ligne sm, x2, y1, x2, y2
    Ligne sm, x2, y2, x1, y2
    Ligne sm, x1, y2, x1, y1
End Sub

Private Sub PoserTexte(swModel As Object, texte As String, x As Double, y As Double)
    Dim note As Object, ann As Object, tf As Object
    On Error GoTo Echec
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
    Dim p As String
    p = GetSetting("DecoupeIsolant", "Config", "Exe", "")
    If p = "" Or Dir(p) = "" Then
        p = InputBox("Chemin complet de DecoupeIsolant.exe :", TITRE, "C:\DecoupeIsolant\DecoupeIsolant.exe")
        If p = "" Then Exit Function
        If Dir(p) = "" Then
            MsgBox "Fichier introuvable : " & p, vbCritical, TITRE
            Exit Function
        End If
        SaveSetting "DecoupeIsolant", "Config", "Exe", p
    End If
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
    numLog = FreeFile
    Open chemin For Output As #numLog
    logOuvert = True
    Journal "=== " & TITRE & " - " & Format$(Now, "dd/mm/yyyy hh:nn:ss") & " ==="
End Sub

Private Sub Journal(s As String)
    If logOuvert Then Print #numLog, s
End Sub

Private Sub FermerJournal()
    If logOuvert Then
        Close #numLog
        logOuvert = False
    End If
End Sub
