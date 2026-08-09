Bake Manager — первая интегрированная версия

Установка:
1. Закрой Substance 3D Painter.
2. Замени папку текущего Python-плагина папкой BakeManager из архива.
3. Убедись, что в папке лежат:
   __init__.py
   asset_manager.py
   Bake_Manager_Icon.png
   bake_templates.json
   ui_state.json
4. Запусти Painter или выполни Reload Plugins.

В этой версии:
- панель и кнопка называются Bake Manager;
- добавлена кнопка с Bake_Manager_Icon.png в панели плагинов;
- Project: создание, переименование и удаление групп настроек;
- Setup: запись текущих bake-параметров, Apply, Re-record, Rename, Duplicate, Delete;
- активные карты Setup отображаются кнопками-чипами и могут отключаться на текущий запуск;
- Bake запускает выбранные Setup для всех Texture Sets;
- результат сохраняется как Set_Setup_Map.png, например Cube_Skew_N.png;
- результат добавляется в папку соответствующего Texture Set в менеджере;
- Clear Mesh Maps очищает назначенные карты через существующий механизм удаления из Project Assets;
- Bake Smart Mat создаёт Smart Material из одной выбранной папки Layers;
- сохранённые Smart Materials можно вставлять и удалять из списка Project.

Ограничение первой версии:
- автоматическая перепривязка источников внутри Smart Material к вариантам Set_Setup_Map пока не реализована.
