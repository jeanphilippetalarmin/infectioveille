#!/usr/bin/env python3
"""Installe uniquement le modèle libre Argos anglais-français (une fois/cache)."""
import sys


def main():
    try:
        import argostranslate.package as packages
        import argostranslate.translate as translation
        installed = {x.code for x in translation.get_installed_languages()}
        if 'en' in installed and 'fr' in installed:
            source = next(x for x in translation.get_installed_languages() if x.code == 'en')
            dest = next(x for x in translation.get_installed_languages() if x.code == 'fr')
            if source.get_translation(dest):
                print('Argos en→fr : modèle déjà disponible dans le cache.')
                return 0
        packages.update_package_index()
        matches = [p for p in packages.get_available_packages()
                   if p.from_code == 'en' and p.to_code == 'fr'
                   and getattr(p, 'type', 'translate') == 'translate']
        if not matches:
            raise RuntimeError('aucun modèle anglais-français dans le catalogue Argos')
        path = matches[0].download()
        packages.install_from_path(path)
        source = next((x for x in translation.get_installed_languages() if x.code == 'en'), None)
        dest = next((x for x in translation.get_installed_languages() if x.code == 'fr'), None)
        if not source or not dest or not source.get_translation(dest):
            raise RuntimeError('modèle installé mais traduction non disponible')
        print('Argos en→fr : modèle installé et disponible.')
        return 0
    except Exception as exc:
        print(f'ÉCHEC installation traduction locale : {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
