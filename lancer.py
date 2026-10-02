"""Point d'entrée de l'application (double-clic = interface ; avec arguments = ligne de commande)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # indispensable pour l'exécutable Windows (calcul multi-processus)
    if len(sys.argv) == 3 and sys.argv[1] == "--autotest":
        from decoupe.autotest import lancer

        raise SystemExit(lancer(sys.argv[2]))
    if len(sys.argv) > 1:
        from decoupe.cli import main

        raise SystemExit(main())
    from decoupe.gui import main

    main()
