import json
import os
import re
import shutil
import sys
import time
import traceback

import mset


JOB = {}
BAKER = None
LAST_RAW_SNAPSHOT = None
STABLE_CHECKS = 0
AO_CONFIGURED_IDS = set()
SUFFIX_WINDOW = None
SUFFIX_FIELD = None
PENDING_SUFFIX_FILES = None
RAW_BATCH_STARTED_AT = None

IMAGE_EXTENSIONS = (
    ".png",
    ".tga",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".exr",
)

MAP_INFO = (
    ("bentnormal", "BN", "Bent Normals"),
    ("worldspacenormal", "WSN", "World Space Normal"),
    ("objectnormal", "WSN", "World Space Normal"),
    ("ambientocclusion", "AO", "Ambient Occlusion"),
    ("aobakermap", "AO", "Ambient Occlusion"),
    ("occlusion", "AO", "Ambient Occlusion"),
    ("curvature", "C", "Curvature"),
    ("thickness", "T", "Thickness"),
    ("position", "P", "Position"),
    ("height", "H", "Height"),
    ("materialid", "ID", "ID Map"),
    ("objectid", "ID", "ID Map"),
    ("groupid", "ID", "ID Map"),
    ("opacity", "O", "Opacity"),
    ("transparency", "O", "Opacity"),
    ("normal", "N", "Normal"),
)


def safe_name(value):
    value = str(value or "Texture_Set").strip()

    for character in '<>:"/\\|?*':
        value = value.replace(character, "_")

    value = value.rstrip(". ")
    return value or "Texture_Set"


def normalized_token(value):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).lower(),
    )


def write_json_atomic(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"

    with open(temporary_path, "w", encoding="utf-8") as stream:
        json.dump(
            payload,
            stream,
            ensure_ascii=False,
            indent=4,
        )

    os.replace(temporary_path, path)


def write_status(state, message, **extra):
    payload = {
        "version": 4,
        "state": state,
        "message": message,
        "updated_at": time.time(),
    }
    payload.update(extra)

    try:
        write_json_atomic(JOB["status_path"], payload)
    except Exception:
        traceback.print_exc()

    print("[PainterBridge] " + message)


def texture_set_names():
    names = []

    try:
        count = int(BAKER.getTextureSetCount())
    except Exception:
        count = 0

    for index in range(count):
        try:
            name = str(BAKER.getTextureSetName(index)).strip()
        except Exception:
            continue

        if name and name not in names:
            names.append(name)

    if not names:
        for name in JOB.get("texture_set_names", []):
            name = str(name).strip()

            if name and name not in names:
                names.append(name)

    return names


def map_code_and_label(map_object):
    identity = normalized_token(
        type(map_object).__name__
        + " "
        + str(getattr(map_object, "suffix", ""))
    )

    for token, code, label in MAP_INFO:
        if token in identity:
            return code, label

    fallback = re.sub(
        r"[^A-Za-z0-9]+",
        "",
        str(getattr(map_object, "suffix", "")),
    ).upper()
    return fallback[:12] or "MAP", fallback[:12] or "Texture"


def configure_map_suffixes():
    configured = []

    for map_object in BAKER.getAllMaps():
        try:
            if not bool(map_object.enabled):
                continue
        except Exception:
            pass

        code, label = map_code_and_label(map_object)

        try:
            map_object.suffix = "_" + code
        except Exception:
            traceback.print_exc()

        configured.append(
            {
                "code": code,
                "label": label,
                "class_name": type(map_object).__name__,
            }
        )

    return configured


def configure_ao_defaults():
    """Apply the requested defaults once to each AO map in this scene."""
    global AO_CONFIGURED_IDS

    configured = 0

    for map_index, map_object in enumerate(
        BAKER.getAllMaps()
    ):
        class_token = normalized_token(
            type(map_object).__name__
        )

        if (
            "aobakermap" not in class_token
            and "ambientocclusion" not in class_token
        ):
            continue

        # Toolbag may return a fresh Python wrapper on every getAllMaps()
        # call, so the stable map index is safer than Python's id().
        map_identity = (
            map_index,
            class_token,
        )

        if map_identity in AO_CONFIGURED_IDS:
            continue

        settings = (
            ("rayCount", 2000),
            ("searchDistance", 0.009),
            ("cosineWeight", -1.0),
            ("floorOcclusion", False),
            ("floor", 0.8),
            ("ignoreGroups", True),
            ("twoSided", False),
            # These two members exist in some Toolbag 5 builds but are not
            # present in every public API revision.
            ("overrideSoften", True),
            ("soften", 0.2),
        )

        for member_name, value in settings:
            if not hasattr(map_object, member_name):
                continue

            try:
                setattr(map_object, member_name, value)
            except Exception:
                pass

        AO_CONFIGURED_IDS.add(map_identity)
        configured += 1

    return configured


def configure_offline_bake_mode():
    """Set Toolbag's Bake Mode scheduling selector to Offline when exposed."""
    # The serialized Toolbag property is named work scheduling (wsched).
    # Public builds have exposed slightly different Python spellings.
    for member_name in (
        "workScheduling",
        "bakeScheduling",
        "scheduling",
        "scheduleMode",
    ):
        if not hasattr(BAKER, member_name):
            continue

        try:
            setattr(BAKER, member_name, "Offline")
            return member_name
        except Exception:
            continue

    return ""


def suffix_history_path():
    return JOB.get("suffix_history_path") or os.path.join(
        os.path.dirname(JOB["manifest_path"]),
        "marmoset_suffix_history.json",
    )


def clean_suffix(value):
    value = str(value or "").strip()
    value = re.sub(r'[<>:"/\\|?*]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("._- ")


def load_suffix_history():
    path = suffix_history_path()

    if not os.path.isfile(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return []

    values = (
        payload.get("suffixes", [])
        if isinstance(payload, dict)
        else payload
    )
    result = []

    for value in values:
        suffix = clean_suffix(value)

        if suffix and suffix.lower() not in {
            item.lower() for item in result
        }:
            result.append(suffix)

    return result


def remember_suffix(suffix):
    suffix = clean_suffix(suffix)

    if not suffix:
        return

    history = [
        item
        for item in load_suffix_history()
        if item.lower() != suffix.lower()
    ]
    history.insert(0, suffix)
    write_json_atomic(
        suffix_history_path(),
        {
            "version": 1,
            "suffixes": history,
        },
    )


def apply_entered_suffix():
    value = ""

    if SUFFIX_FIELD is not None:
        try:
            value = SUFFIX_FIELD.value
        except Exception:
            pass

    finish_suffix_choice(value)


def finish_suffix_choice(value):
    global SUFFIX_WINDOW
    global SUFFIX_FIELD
    global PENDING_SUFFIX_FILES
    global LAST_RAW_SNAPSHOT
    global STABLE_CHECKS
    global RAW_BATCH_STARTED_AT

    suffix = clean_suffix(value)
    pending_files = list(PENDING_SUFFIX_FILES or [])

    if suffix:
        remember_suffix(suffix)

    if SUFFIX_WINDOW is not None:
        try:
            SUFFIX_WINDOW.close()
        except Exception:
            pass

    SUFFIX_WINDOW = None
    SUFFIX_FIELD = None
    PENDING_SUFFIX_FILES = None
    LAST_RAW_SNAPSHOT = None
    STABLE_CHECKS = 0
    RAW_BATCH_STARTED_AT = None

    if pending_files:
        organize_raw_outputs(
            pending_files,
            suffix=suffix,
        )


def show_suffix_prompt(raw_files):
    global SUFFIX_WINDOW
    global SUFFIX_FIELD
    global PENDING_SUFFIX_FILES

    PENDING_SUFFIX_FILES = [
        dict(item) for item in raw_files
    ]
    SUFFIX_WINDOW = mset.UIWindow("Bake Suffix")

    try:
        SUFFIX_WINDOW.width = 380
    except Exception:
        pass

    prompt = mset.UILabel(
        "What suffix should be added?"
    )
    SUFFIX_WINDOW.addElement(prompt)
    SUFFIX_WINDOW.addReturn()

    SUFFIX_FIELD = mset.UITextField()
    SUFFIX_FIELD.value = ""
    SUFFIX_FIELD.width = 250
    SUFFIX_WINDOW.addElement(SUFFIX_FIELD)
    SUFFIX_WINDOW.addReturn()

    apply_button = mset.UIButton("Apply Suffix")
    apply_button.onClick = apply_entered_suffix
    SUFFIX_WINDOW.addElement(apply_button)

    no_suffix_button = mset.UIButton("No Suffix")
    no_suffix_button.onClick = lambda: finish_suffix_choice("")
    SUFFIX_WINDOW.addElement(no_suffix_button)
    SUFFIX_WINDOW.addReturn()

    history = load_suffix_history()
    history_label = mset.UILabel(
        "Previous suffixes:"
    )
    SUFFIX_WINDOW.addElement(history_label)
    SUFFIX_WINDOW.addReturn()

    if history:
        for saved_suffix in history:
            suffix_button = mset.UIButton(
                saved_suffix
            )
            suffix_button.onClick = (
                lambda value=saved_suffix: (
                    finish_suffix_choice(value)
                )
            )
            SUFFIX_WINDOW.addElement(
                suffix_button
            )
            SUFFIX_WINDOW.addReturn()
    else:
        empty_label = mset.UILabel(
            "No saved suffixes yet."
        )
        SUFFIX_WINDOW.addElement(empty_label)

    write_status(
        "waiting_suffix",
        "Bake complete. Waiting for a naming suffix.",
        raw_file_count=len(raw_files),
    )


def ensure_bake_settings():
    """Keep native Toolbag Bake settings aligned with the Painter project."""
    applied = False

    if hasattr(BAKER, "multipleTextureSets"):
        try:
            BAKER.multipleTextureSets = True
            applied = bool(BAKER.multipleTextureSets)
        except Exception:
            pass

    if hasattr(BAKER, "tileMode"):
        # Toolbag 5 documents tileMode as an integer: 0 Single, 1 Multiple,
        # 2 UDIM. The legacy boolean above is kept for older 5.x builds.
        try:
            BAKER.tileMode = 1
            applied = True
        except Exception:
            pass

    BAKER.outputPath = JOB["raw_output_path"]

    try:
        BAKER.outputBits = 16
    except Exception:
        pass

    try:
        BAKER.useHiddenMeshes = True
    except Exception:
        pass

    configured_maps = configure_map_suffixes()
    configure_ao_defaults()
    return applied, configured_maps


def choose_texture_set(file_name, names):
    file_token = normalized_token(
        os.path.splitext(file_name)[0]
    )
    matches = []

    for name in names:
        token = normalized_token(name)

        if token and token in file_token:
            matches.append((len(token), name))

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    if len(names) == 1:
        return names[0]

    return "Unmatched"


def infer_map_type(file_name):
    stem = normalized_token(
        os.path.splitext(file_name)[0]
    )

    for token, code, label in MAP_INFO:
        if token in stem:
            return code, label

    raw_stem = os.path.splitext(file_name)[0]

    for _token, code, label in MAP_INFO:
        if re.search(
            r"(?:^|[_\-.])"
            + re.escape(code)
            + r"(?:[_\-.]|$)",
            raw_stem,
            re.IGNORECASE,
        ):
            return code, label

    return "MAP", "Texture"


def collect_raw_output_files():
    output_root = JOB["output_root"]
    result = []

    if not os.path.isdir(output_root):
        return result

    for file_name in os.listdir(output_root):
        file_path = os.path.join(output_root, file_name)

        if not os.path.isfile(file_path):
            continue

        if os.path.splitext(file_name)[1].lower() not in IMAGE_EXTENSIONS:
            continue

        try:
            modified = os.path.getmtime(file_path)
            size_bytes = os.path.getsize(file_path)
        except OSError:
            continue

        if modified < JOB.get("launched_at", 0.0) - 2.0:
            continue

        result.append(
            {
                "path": os.path.normpath(file_path),
                "file_name": file_name,
                "modified": modified,
                "size_bytes": size_bytes,
            }
        )

    result.sort(key=lambda item: item["path"].lower())
    return result


def raw_snapshot(files):
    return tuple(
        (
            item["path"],
            item["modified"],
            item["size_bytes"],
        )
        for item in files
    )


def expected_output_pairs():
    """Return every Texture Set/map pair expected from one native bake."""
    names = texture_set_names()
    map_codes = []

    for map_object in BAKER.getAllMaps():
        try:
            if not bool(map_object.enabled):
                continue
        except Exception:
            pass

        code, _label = map_code_and_label(
            map_object
        )

        if code not in map_codes:
            map_codes.append(code)

    return {
        (texture_set, map_code)
        for texture_set in names
        for map_code in map_codes
    }


def observed_output_pairs(raw_files):
    names = texture_set_names()
    return {
        (
            choose_texture_set(
                raw["file_name"],
                names,
            ),
            infer_map_type(
                raw["file_name"]
            )[0],
        )
        for raw in raw_files
    }


def scan_organized_files():
    records = []
    output_root = JOB["output_root"]

    if not os.path.isdir(output_root):
        return records

    for texture_set in os.listdir(output_root):
        marmoset_directory = os.path.join(
            output_root,
            texture_set,
            "Marmoset",
        )

        if not os.path.isdir(marmoset_directory):
            continue

        for file_name in os.listdir(marmoset_directory):
            file_path = os.path.join(
                marmoset_directory,
                file_name,
            )

            if (
                not os.path.isfile(file_path)
                or os.path.splitext(file_name)[1].lower()
                not in IMAGE_EXTENSIONS
            ):
                continue

            _map_code, map_label = infer_map_type(file_name)
            records.append(
                {
                    "path": os.path.normpath(file_path),
                    "file_name": file_name,
                    "texture_set": texture_set,
                    "map_type": map_label,
                    "manager_folder": texture_set + "/Marmoset",
                }
            )

    records.sort(key=lambda item: item["path"].lower())
    return records


def organize_raw_outputs(raw_files, suffix=""):
    names = texture_set_names()
    moved = []
    suffix = clean_suffix(suffix)

    for raw in raw_files:
        texture_set = choose_texture_set(
            raw["file_name"],
            names,
        )
        map_code, map_label = infer_map_type(
            raw["file_name"]
        )
        safe_set = safe_name(texture_set)
        destination_directory = os.path.join(
            JOB["output_root"],
            safe_set,
            "Marmoset",
        )
        os.makedirs(destination_directory, exist_ok=True)
        extension = os.path.splitext(raw["file_name"])[1].lower()
        destination_path = os.path.join(
            destination_directory,
            safe_set
            + "_"
            + map_code
            + ("_" + suffix if suffix else "")
            + extension,
        )

        try:
            # os.replace performs one atomic overwrite and is reliable for
            # repeated bakes.  If Painter briefly holds the old preview, the
            # raw file stays in place and the periodic watcher retries it.
            os.replace(raw["path"], destination_path)
        except OSError:
            try:
                shutil.copy2(raw["path"], destination_path)
                os.remove(raw["path"])
            except OSError:
                traceback.print_exc()
                continue

        moved.append(
            {
                "path": os.path.normpath(destination_path),
                "file_name": os.path.basename(destination_path),
                "texture_set": texture_set,
                "map_type": map_label,
                "manager_folder": texture_set + "/Marmoset",
            }
        )

    if not moved:
        return

    all_records = scan_organized_files()
    generation = time.time()
    write_json_atomic(
        JOB["manifest_path"],
        {
            "version": 4,
            "source": "Marmoset Toolbag 5",
            "generation": generation,
            "painter_project": JOB.get("painter_project", ""),
            "texture_set_names": names,
            "output_directory": JOB["output_root"],
            "files": all_records,
        },
    )
    write_status(
        "baked",
        "Native Toolbag bake organized for Painter: "
        + str(len(moved))
        + " map(s).",
        manifest_path=JOB["manifest_path"],
        output_directory=JOB["output_root"],
        file_count=len(moved),
        suffix=suffix,
    )

    return len(moved)


def periodic_update():
    global LAST_RAW_SNAPSHOT
    global STABLE_CHECKS
    global SUFFIX_WINDOW
    global PENDING_SUFFIX_FILES
    global RAW_BATCH_STARTED_AT

    try:
        ensure_bake_settings()

        if PENDING_SUFFIX_FILES is not None:
            window_is_visible = True

            if SUFFIX_WINDOW is not None:
                try:
                    window_is_visible = bool(
                        SUFFIX_WINDOW.visible
                    )
                except Exception:
                    pass

            if window_is_visible:
                return

            # Closing the prompt with X does not discard the bake. Reopen it
            # so the maps can never be silently imported with a wrong name.
            show_suffix_prompt(
                PENDING_SUFFIX_FILES
            )
            return

        raw_files = collect_raw_output_files()

        if not raw_files:
            LAST_RAW_SNAPSHOT = None
            STABLE_CHECKS = 0
            RAW_BATCH_STARTED_AT = None
            return

        if RAW_BATCH_STARTED_AT is None:
            RAW_BATCH_STARTED_AT = time.time()
            write_status(
                "collecting_outputs",
                "Collecting all Texture Set maps before asking for a suffix.",
                raw_file_count=len(raw_files),
            )

        snapshot = raw_snapshot(raw_files)

        if snapshot == LAST_RAW_SNAPSHOT:
            STABLE_CHECKS += 1
        else:
            LAST_RAW_SNAPSHOT = snapshot
            STABLE_CHECKS = 0

        newest_write = max(
            item["modified"]
            for item in raw_files
        )
        expected_pairs = expected_output_pairs()
        observed_pairs = observed_output_pairs(
            raw_files
        )
        has_complete_batch = (
            bool(expected_pairs)
            and expected_pairs.issubset(
                observed_pairs
            )
        )
        batch_wait_timed_out = (
            RAW_BATCH_STARTED_AT is not None
            and time.time() - RAW_BATCH_STARTED_AT
            >= 15.0
        )

        # Native Bake has no public completion callback. Offline mode returns
        # control only after baking, then these extra checks ensure all map
        # files are closed before the suffix prompt appears.
        if (
            STABLE_CHECKS >= 4
            and time.time() - newest_write >= 2.0
            and (
                has_complete_batch
                or batch_wait_timed_out
            )
        ):
            show_suffix_prompt(raw_files)

    except Exception as error:
        traceback.print_exc()
        write_status(
            "error",
            "Marmoset bridge error: " + str(error),
            traceback=traceback.format_exc(),
        )


def restore_bridge_after_scene_load():
    """Reconnect callbacks and defaults when the saved bridge scene reloads."""
    global BAKER
    global AO_CONFIGURED_IDS
    global LAST_RAW_SNAPSHOT
    global STABLE_CHECKS

    expected_scene = JOB.get("scene_path", "")

    if expected_scene:
        try:
            loaded_scene = mset.getScenePath()
        except Exception:
            loaded_scene = ""

        if (
            loaded_scene
            and os.path.normcase(
                os.path.abspath(loaded_scene)
            )
            != os.path.normcase(
                os.path.abspath(expected_scene)
            )
        ):
            return

    candidates = []

    for scene_object in mset.getAllObjects():
        try:
            is_baker = isinstance(
                scene_object,
                mset.BakerObject,
            )
        except Exception:
            is_baker = (
                type(scene_object).__name__
                == "BakerObject"
            )

        if is_baker:
            candidates.append(scene_object)

    if not candidates:
        return

    wanted_name = str(
        JOB.get("baker_name", "")
    ).strip().lower()
    BAKER = next(
        (
            candidate
            for candidate in candidates
            if str(
                getattr(candidate, "name", "")
            ).strip().lower() == wanted_name
        ),
        candidates[0],
    )
    AO_CONFIGURED_IDS = set()
    LAST_RAW_SNAPSHOT = None
    STABLE_CHECKS = 0
    configure_offline_bake_mode()
    ensure_bake_settings()
    mset.callbacks.onPeriodicUpdate = periodic_update

    write_status(
        "ready",
        "Saved Bake Project reloaded. Offline mode and Painter Bridge "
        "settings restored.",
        scene_path=expected_scene,
    )


def create_quick_loader_project():
    global BAKER

    low_paths = [
        os.path.normpath(path)
        for path in JOB.get("low_poly_paths", [])
        if os.path.isfile(path)
    ]
    high_paths = [
        os.path.normpath(path)
        for path in JOB.get("high_poly_paths", [])
        if os.path.isfile(path)
    ]

    if not low_paths:
        raise RuntimeError("No valid low-poly mesh was supplied.")

    if not high_paths:
        raise RuntimeError("No valid high-poly mesh was supplied.")

    os.makedirs(JOB["output_root"], exist_ok=True)
    os.makedirs(
        os.path.dirname(JOB["manifest_path"]),
        exist_ok=True,
    )

    mset.newScene()
    BAKER = mset.BakerObject()
    BAKER.name = JOB.get("baker_name", "Painter Bake Project")

    # BakerObject.importModel is Toolbag's public Quick Loader API. It reads
    # _high/_low object suffixes and creates every matching Bake Group.
    for path in low_paths + high_paths:
        BAKER.importModel(path)

    offline_member = configure_offline_bake_mode()
    multiple_sets_applied, configured_maps = ensure_bake_settings()

    try:
        BAKER.collapsed = False
    except Exception:
        pass

    try:
        mset.setSelectedObjects([BAKER])
    except Exception:
        pass

    try:
        mset.frameScene()
    except Exception:
        pass

    scene_path = JOB.get("scene_path", "")

    if scene_path:
        os.makedirs(os.path.dirname(scene_path), exist_ok=True)
        mset.saveScene(scene_path)

    mset.callbacks.onPeriodicUpdate = periodic_update
    mset.callbacks.onSceneLoaded = (
        restore_bridge_after_scene_load
    )

    write_status(
        "ready",
        "Quick Loader created the native Bake Project. Use Toolbag's Start "
        "button; outputs will be organized for Painter automatically.",
        scene_path=scene_path,
        output_directory=JOB["output_root"],
        raw_output_path=JOB["raw_output_path"],
        texture_sets=texture_set_names(),
        multiple_texture_sets=multiple_sets_applied,
        bake_mode="Offline",
        bake_mode_member=offline_member,
        ao_defaults={
            "rayCount": 2000,
            "searchDistance": 0.009,
            "cosineWeight": -1.0,
            "floorOcclusion": False,
            "floor": 0.8,
            "ignoreGroups": True,
            "twoSided": False,
        },
        maps=configured_maps,
        low_poly_paths=low_paths,
        high_poly_paths=high_paths,
    )


def main():
    global JOB

    if len(sys.argv) < 2:
        raise RuntimeError("Bridge job path was not supplied.")

    with open(
        os.path.abspath(sys.argv[1]),
        "r",
        encoding="utf-8",
    ) as stream:
        JOB = json.load(stream)

    create_quick_loader_project()


try:
    main()
except Exception as error:
    traceback.print_exc()

    if JOB:
        write_status(
            "error",
            str(error),
            traceback=traceback.format_exc(),
        )
