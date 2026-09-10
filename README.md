<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/Logo_Dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/Logo_Light.png">
    <img alt="Bake Manager" src="docs/Logo_Light.png" width="890">
  </picture>
</p>

<p align="center">
  <strong>Language:</strong>
  <a href="README.md">English</a> |
  <a href="README_RU.md">Русский</a>
</p>

<img width="18" height="18" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> **Bake Manager** is a plugin that helps prepare your scene for combining baked maps and keeps the entire process organized.

It is designed for vehicles and other complex assets that use several Texture Sets.

> [!NOTE]
>
> Developed and tested with **Substance 3D Painter 11.1.3** and **Marmoset Toolbag 5.02** on Windows.

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> What does it do?

- Organizes textures into Texture Set folders for clearer visual navigation.
- `Live Project Folder` - keeps project files synchronized with the folders Explorer. 
- Saves baking `Projects` and `Setups` as presets that can be quickly reused in new projects.
- Automatically renames maps after baking using the Texture Set name, preset name, and map type.
- `Marmoset Bridge` - creates a Marmoset Toolbag scene for quick bake adjustments.
- Smart Material that can be applied to all Texture Sets at once.
- Automatically assigns textures to layers based on their filenames. 

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/bbb8be4b-93f2-487c-9903-20b655e095f5"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/93bb88c2-f13a-4932-b72f-3497a7031c79

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Live Project Folder

Automatically exports maps after baking to the location of the `.spp` file, preserving the same folder structure as in the plugin. Add files through Explorer or export them from other applications, and they appear directly in Bake Manager.
> [!NOTE]
>
> The plugin’s features only work when you click `Bake Setups`, not the `Bake` blue button in Painter’s Baking window.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/1cf48ac4-5615-4456-b6b9-f6964d85d149"
    alt="Better Visuals"
    width="2064"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/d5736dd5-088e-499f-a777-4e7646e91ad4

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Automatic Naming

Automatically names baked maps using their Texture Set, map type, and Setup. This prevents Substance 3D Painter from overwriting previous bakes that would otherwise need to be renamed manually.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/22a0654c-51fe-487f-bcf5-ce0df9d3fd6a"
    alt="Bake Manager demonstration"
    width="3440"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/d6a2e256-ad3f-4d47-b848-5819fe839b52

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Automatic Map Assignment

Automatically assign baked maps to the matching layers and Texture Sets. The file name shows where to place the map. For example, `Cube_N_Base` goes to `Cube` folder in `N` subfolder and `Base` layer.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/799083bb-65fb-445d-b282-f5f26ff14bd2"
    alt="Bake Manager demonstration"
    width="2064"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/6edfc395-be75-4535-9fd3-a2e0aab5d75a

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Projects and Setups

Organize reusable baking settings into Projects and Setups.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/61948782-b6d5-4fdf-be8d-60a81199b335"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/1b635dd1-c169-47e9-b2f0-869359585c92

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Marmoset Bridge

Сreates a Marmoset bake scene using meshes and Texture Set settings from Painter and send the renamed maps back.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/967e0ae6-5f52-4533-b282-4f62d2b8891e"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/5686078b-1b1e-48e3-b885-8f2935c2eb6d

</details>

Click a low-poly mesh to open its Bake Group cage settings, adjust Offset or Skew.

> [!NOTE]
>
> It's function not working if you in paint mode skew or cage, you need press `Q` and select meshes

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/007a9aa0-b771-4aee-93d4-3b2e773dec16"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/c6e1bf49-cc4c-40f3-8850-662e934e859b

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Smart Materials

Create, save, and apply Smart Materials to all Texture Sets **at once**.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/794fc67d-3efd-44f5-8ad2-69216e5b4df6"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/162f4802-b982-492d-b733-b1a3deff06af

</details>

# <img width="24" height="24" alt="Image" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Installation

```text
C:\Users\<User>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/0039e8a1-2eef-4938-beec-79f698f6af8c"
    alt="Bake Manager demonstration"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Watch the full video</strong></summary>

https://github.com/user-attachments/assets/12e3b201-a1e7-4d98-b9e8-38b8df3f4e27

</details>

<p align="center">
  <a href="https://github.com/skazochnik3d/Bake-Manager/releases/latest">
    <img
      src="docs/Download_Button.png"
      alt="Download Bake Manager"
      width="350"
    >
  </a>
</p>
