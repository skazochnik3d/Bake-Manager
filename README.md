# Bake Manager

**Bake Manager** is a production plugin for **Adobe Substance 3D Painter** that automates multi-Texture-Set mesh-map baking, file organization, layer assignment, reusable bake setups, Smart Materials, and a Marmoset Toolbag bridge.

It is designed primarily for vehicles and other complex assets that use several Texture Sets and require repeated Base, Skew, Local, Cage, Fix, and other bake passes.

> Current plugin version: **1.0.0**  
> Developed and tested primarily with **Substance 3D Painter 11.1.3** on Windows.

## Features

### Batch Bake Setups

- Save multiple reusable baking configurations as **Setups**.
- Run every checked Setup across all Texture Sets.
- Choose output resolution and antialiasing separately for each Setup.
- Enable or disable individual mesh maps per Setup.
- Keep Bake Projects available between Painter scenes.

### Automatic naming and organization

Generated maps use a predictable format:

```text
<TextureSet>_<Map>_<Setup>.png
```

Examples:

```text
Cab_N_Base.png
Cab_AO_Local.png
Set_01_N_Fix_01.png
```

Maps are organized into project and Texture Set folders automatically.

### Automatic layer assignment

Bake Manager can route exported maps into a matching Smart Material hierarchy:

```text
Texture Set / Map / Setup
```

Setup names can describe nested folders:

```text
Fix_01
```

resolves to:

```text
Set_01 / N / Fix / 01
```

Deeper paths are also supported:

```text
Fix_Local_01
```

can resolve to:

```text
Set_01 / N / Fix / Local / 01
```

Pressing **Refresh** checks existing assignments again, so a newly created target layer can receive an already baked map without running another bake.

### Smart Materials

- Save private `.spsm` files directly from the plugin.
- Keep the user-provided Smart Material name unchanged.
- Add one saved Smart Material to every Texture Set.
- Prevent temporary or private materials from remaining as duplicates in Painter Assets.

### Marmoset Toolbag bridge

Bake Manager includes a bridge for preparing and receiving bake data from **Marmoset Toolbag 5**.

## Installation

1. Download `BakeManager.zip` from the latest GitHub Release.
2. Close Substance 3D Painter.
3. Extract the `BakeManager` folder into:

```text
C:\Users\<User>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

The resulting structure should be:

```text
python/
└── plugins/
    └── BakeManager/
        ├── __init__.py
        ├── bake_manager.py
        ├── Bake_Manager_Icon.png
        └── README_RU.txt
```

4. Start Substance 3D Painter.
5. Open the **Plugins** menu and enable **Bake Manager** if it is not already enabled.

## Automatic update notifications

Bake Manager checks the repository's latest published GitHub Release shortly after the plugin starts.

When a newer version is available, the plugin shows:

- installed and available version numbers;
- release notes;
- **Download**;
- **Later**;
- **Skip This Version**.

**Download** opens the attached `BakeManager.zip` release asset. The plugin does not silently replace its own files while Painter is running.

The updater expects each stable release to contain an asset named exactly:

```text
BakeManager.zip
```

## Publishing a new release

1. Change `PLUGIN_VERSION` in `bake_manager.py`:

```python
PLUGIN_VERSION = "1.1.0"
```

2. Prepare the release archive with this structure:

```text
BakeManager.zip
└── BakeManager/
    ├── __init__.py
    ├── bake_manager.py
    ├── Bake_Manager_Icon.png
    └── README_RU.txt
```

3. On GitHub, create a new Release.
4. Use a semantic version tag, for example:

```text
v1.1.0
```

5. Add the changelog to the Release description.
6. Attach the archive with the exact name `BakeManager.zip`.
7. Publish it as a normal release, not a draft or prerelease.

The installed `1.0.0` plugin will then detect `v1.1.0` automatically.

## User data

Do not include personal working data in a public release or commit:

```text
BakeProject__*.json
BakeProject__*.json.bak
*.spsm
ui_state.json
.ignore_assets_pt
```

These files may contain personal Setups, UI state, and private Smart Materials.

## Recommended Setup naming

Simple pass:

```text
Base
Skew
Local
Cage
```

Nested pass:

```text
Fix_01
Fix_02
Fix_Local_01
```

Explicit slash paths are also supported:

```text
Fix/Local/01
```

## Repository

- Issues and bug reports: use the repository **Issues** tab.
- Stable downloads: use **Releases**.
- Main plugin file: `BakeManager/bake_manager.py`.

## License

No license has been selected yet. Until a license is added, redistribution and modification rights are not automatically granted. Add a `LICENSE` file before wider public distribution.
