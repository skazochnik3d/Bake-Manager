<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/Logo_Dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/Logo_Light.png">
    <img alt="Bake Manager" src="docs/Logo_Light.png" width="890">
  </picture>
</p>

<p align="center">
  <strong>Язык:</strong>
  <a href="README.md">English</a> |
  <a href="README_RU.md">Русский</a>
</p>

<img width="18" height="18" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> **Bake Manager** — это плагин, который помогает подготовить сцену к сведению запечённых карт и упорядочивает весь процесс.

Он предназначен для работы с автомобилями и другими сложными моделями, использующими несколько текстурных сетов.

> [!NOTE]
>
> Разработано и протестировано с **Substance 3D Painter 11.1.3** и **Marmoset Toolbag 5.02** на Windows.

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Что умеет плагин?

- Распределяет текстуры по папкам текстурных сетов для более удобной навигации.
- `Папка проекта` - синхронизирует файлы проекта с папками в Проводнике.
- Сохраняет `Projects` и `Setups` с настройками запекания в виде пресетов для быстрого использования в новых проектах.
- Автоматически переименовывает карты после запекания, используя название текстурного сета, пресета и тип карты.
- `Marmoset Bridge` - создаёт сцену Marmoset Toolbag для быстрого исправления запекания.
- Создаёт Smart Material, который можно применить сразу ко всем текстурным сетам.
- Автоматически назначает текстуры в слои по именам файлов.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/bbb8be4b-93f2-487c-9903-20b655e095f5"
    alt="Демонстрация Bake Manager"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/93bb88c2-f13a-4932-b72f-3497a7031c79

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Папка проекта

Автоматически экспортирует карты после запекания рядом с файлом `.spp`, сохраняя такую же структуру папок, как в плагине. Добавляйте файлы через Проводник или экспортируйте их из других программ - они появятся прямо в Bake Manager.

> [!NOTE]
>
> Функции плагина работают только при нажатии `Bake Setups`, а не синей кнопки `Bake` в окне запекания Painter.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/1cf48ac4-5615-4456-b6b9-f6964d85d149"
    alt="Папка проекта"
    width="2064"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/d5736dd5-088e-499f-a777-4e7646e91ad4

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Автоматическое переименование

Автоматически называет запечённые карты, используя название текстурного сета, тип карты и Setup. Благодаря этому Substance 3D Painter не перезаписывает предыдущие запекания, которые иначе пришлось бы переименовывать вручную.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/22a0654c-51fe-487f-bcf5-ce0df9d3fd6a"
    alt="Автоматическое переименование"
    width="3440"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/d6a2e256-ad3f-4d47-b848-5819fe839b52

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Автоматическое назначение карт

Автоматически назначает запечённые карты в подходящие слои и текстурные сеты. Имя файла указывает, куда нужно поместить карту. Например, `Cube_N_Base` назначится в папку `Cube`, затем в подпапку `N` и слой `Base`.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/799083bb-65fb-445d-b282-f5f26ff14bd2"
    alt="Автоматическое назначение карт"
    width="2064"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/6edfc395-be75-4535-9fd3-a2e0aab5d75a

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Проекты и настройки

Организуйте повторно используемые настройки запекания с помощью Projects и Setups.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/61948782-b6d5-4fdf-be8d-60a81199b335"
    alt="Проекты и настройки"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/1b635dd1-c169-47e9-b2f0-869359585c92

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Marmoset Bridge

Создаёт сцену для запекания в Marmoset, используя меши и настройки текстурных сетов из Painter, а затем отправляет переименованные карты обратно.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/967e0ae6-5f52-4533-b282-4f62d2b8891e"
    alt="Создание сцены Marmoset"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/5686078b-1b1e-48e3-b885-8f2935c2eb6d

</details>

Нажмите на low-poly меш, чтобы открыть настройки кейджа его Bake Group и изменить Offset или Skew.

> [!NOTE]
>
> Эта функция не работает в режиме рисования Skew или Cage. Нажмите `Q`, а затем выберите нужный меш.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/007a9aa0-b771-4aee-93d4-3b2e773dec16"
    alt="Быстрое редактирование кейджа"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/c6e1bf49-cc4c-40f3-8850-662e934e859b

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Smart Materials

Создавайте, сохраняйте и применяйте Smart Materials сразу ко всем текстурным сетам.

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/794fc67d-3efd-44f5-8ad2-69216e5b4df6"
    alt="Smart Materials"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/162f4802-b982-492d-b733-b1a3deff06af

</details>

# <img width="24" height="24" alt="Иконка Bake Manager" src="https://github.com/user-attachments/assets/33be734e-52f9-4f33-944a-1e3c509d2bd5" /> Установка

Скопируйте папку плагина по следующему пути:

```text
C:\Users\<User>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

<p align="center">
  <img
    src="https://github.com/user-attachments/assets/0039e8a1-2eef-4938-beec-79f698f6af8c"
    alt="Установка Bake Manager"
    width="1238"
  >
</p>

<details>
<summary><strong>▶ Посмотреть полное видео</strong></summary>

https://github.com/user-attachments/assets/12e3b201-a1e7-4d98-b9e8-38b8df3f4e27

</details>

<p align="center">
  <a href="https://github.com/skazochnik3d/Bake-Manager/releases/latest">
    <img
      src="docs/Download_Button.png"
      alt="Скачать Bake Manager"
      width="350"
    >
  </a>
</p>

