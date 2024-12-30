# Snap Store TUI
[![Get it from the Snap Store](https://snapcraft.io/en/dark/install.svg)](https://snapcraft.io/store-tui)

A TUI for for navigating the Snap Store.

Designed using the "Textual" Python Library - https://github.com/textualize/textual/

## Features
- [✅] Browse the Snap Store
- [✅] Search for Snaps
- [✅] View Snap Details
- [✅] Open Store URL in Browser
- [✅] View Installed Snaps
- [✅] Install/Uninstall Snaps directly from the TUI
- [✅] Browse Snap Channels
- [❌] View Snap Revisions
- [❌] Sort and Filter Snaps
- [❌] Install from alternate stores

## Install
```bash
sudo snap install store-tui --edge
```

## Pydantic Schema Generation

Using docs from [snapcraft.io docs](https://api.snapcraft.io/docs/), and  [datamodel-codegen](https://docs.pydantic.dev/latest/integrations/datamodel_code_generator/) utility, I generate pydantic models for the route responses