#!/usr/bin/env python3
"""Apply the Isaac save-state prototype to a pinned Ruffle checkout.

This patch deliberately uses text/AST-light edits rather than a fragile fixed
unified diff so the workflow can emit a useful failure if upstream changes.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


def die(msg: str) -> None:
    print(f"PATCH ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected 1 match in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {label}")


def add_serde_to_type(path: Path, type_name: str) -> bool:
    text = path.read_text(encoding="utf-8")
    type_pat = re.compile(rf"\b(?:pub\s+)?(?:struct|enum)\s+{re.escape(type_name)}\b")
    m = type_pat.search(text)
    if not m:
        return False

    # Search backward a reasonable distance for the immediately preceding derive.
    before = text[max(0, m.start() - 1200):m.start()]
    derives = list(re.finditer(r"#\[derive\((.*?)\)\]", before, re.S))
    if not derives:
        die(f"Could not find derive attribute for {type_name} in {path}")
    d = derives[-1]
    inside = d.group(1)
    if "serde::Serialize" in inside and "serde::Deserialize" in inside:
        return True
    if "Deserialize" in inside and "serde::Serialize" not in inside:
        new_inside = inside.replace("Deserialize", "serde::Serialize, Deserialize", 1)
    else:
        new_inside = inside.rstrip() + ", serde::Serialize, serde::Deserialize"
    start = max(0, m.start() - 1200) + d.start(1)
    end = max(0, m.start() - 1200) + d.end(1)
    text = text[:start] + new_inside + text[end:]
    path.write_text(text, encoding="utf-8")
    print(f"patched serde derives for {type_name} in {path.relative_to(ROOT)}")
    return True


def find_type(name: str) -> Path | None:
    for path in CORE.rglob("*.rs"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(rf"\b(?:pub\s+)?(?:struct|enum)\s+{re.escape(name)}\b", text):
            return path
    return None


def patch_dependencies() -> None:
    path = CORE / "Cargo.toml"
    text = path.read_text(encoding="utf-8")
    root_cargo = ROOT / "Cargo.toml"
    root = root_cargo.read_text(encoding="utf-8")
    has_ws_serde = re.search(r"(?m)^\s*serde\s*=", root) is not None
    has_ws_json = re.search(r"(?m)^\s*serde_json\s*=", root) is not None

    lines = []
    if not re.search(r"(?m)^\s*serde\s*=", text):
        lines.append('serde = { workspace = true, features = ["derive"] }' if has_ws_serde else 'serde = { version = "1.0", features = ["derive"] }')
    if not re.search(r"(?m)^\s*serde_json\s*=", text):
        lines.append('serde_json = { workspace = true }' if has_ws_json else 'serde_json = "1.0"')
    if not lines:
        print("serde dependencies already present")
        return
    marker = "[dependencies]\n"
    if marker not in text:
        die("core/Cargo.toml has no [dependencies] section")
    text = text.replace(marker, marker + "\n".join(lines) + "\n", 1)
    path.write_text(text, encoding="utf-8")
    print("patched core serde dependencies")


def patch_rng() -> None:
    path = CORE / "src" / "avm_rng.rs"
    text = path.read_text(encoding="utf-8")
    old = """#[derive(Debug, Default)]\npub struct AvmRng {\n    u_value: u32,\n}"""
    new = """#[derive(Debug, Default)]\npub struct AvmRng {\n    u_value: u32,\n    initial_seed: Option<u32>,\n}"""
    replace_once(path, old, new, "RNG state field")
    old = """    fn init_with_seed(&mut self, seed: u32) {\n        self.u_value = seed;\n    }"""
    new = """    fn init_with_seed(&mut self, seed: u32) {\n        self.u_value = seed;\n        self.initial_seed = Some(seed);\n    }\n\n    pub fn initial_seed(&self) -> Option<u32> {\n        self.initial_seed\n    }\n\n    pub fn restore_initial_seed(&mut self, seed: u32) {\n        self.u_value = seed;\n        self.initial_seed = Some(seed);\n    }"""
    replace_once(path, old, new, "RNG seed accessors")


def patch_events() -> None:
    wanted = [
        "PlayerEvent",
        "MouseWheelDelta",
        "MouseButton",
        "GamepadButton",
        "ImeEvent",
        "TextControlCode",
        "KeyDescriptor",
        "PhysicalKey",
        "LogicalKey",
        "NamedKey",
    ]
    for name in wanted:
        path = find_type(name)
        if path is None:
            die(f"Could not find event type {name}")
        add_serde_to_type(path, name)


def patch_player() -> None:
    path = CORE / "src" / "player.rs"
    text = path.read_text(encoding="utf-8")

    # Insert the serializable state envelope before Player.
    marker = "pub struct Player {"
    if "struct SavestateEvent" not in text:
        insert = """#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]\nstruct SavestateEvent {\n    frame: u64,\n    event: PlayerEvent,\n}\n\n#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]\nstruct Savestate {\n    version: u32,\n    frame: u64,\n    rng_seed: Option<u32>,\n    events: Vec<SavestateEvent>,\n}\n\n"""
        text = text.replace(marker, insert + marker, 1)
        print("patched savestate data structures")

    # Add recorder fields beside the normal input manager.
    m = re.search(r"(pub struct Player \{.*?\n\s*input:[^\n]+,\n)", text, re.S)
    if not m:
        die("Could not locate Player input field")
    field_block = """\n    // Deterministic replay state (prototype save-state implementation).\n    savestate_frame: u64,\n    savestate_replaying: bool,\n    savestate_target_frame: u64,\n    savestate_input_index: usize,\n    savestate_events: Vec<SavestateEvent>,\n    savestate_recording: bool,\n"""
    if "savestate_frame: u64" not in text[m.start():m.end()+5000]:
        text = text[:m.end()] + field_block + text[m.end():]
        print("patched Player savestate fields")

    # Initialize recorder fields in the Player constructor.
    m = re.search(r"(Mutex::new\(Player \{.*?\n\s*input:[^\n]+,\n)", text, re.S)
    if not m:
        die("Could not locate Player constructor input field")
    init_block = """\n                savestate_frame: 0,\n                savestate_replaying: false,\n                savestate_target_frame: 0,\n                savestate_input_index: 0,\n                savestate_events: Vec::new(),\n                savestate_recording: true,\n"""
    ctor_piece = text[m.start():m.end()+3000]
    if "savestate_frame: 0" not in ctor_piece:
        text = text[:m.end()] + init_block + text[m.end():]
        print("patched Player constructor")

    # Add event recording to handle_event.
    old = """    pub fn handle_event(&mut self, event: PlayerEvent) -> bool {\n        match event {"""
    new = """    pub fn handle_event(&mut self, event: PlayerEvent) -> bool {\n        if self.savestate_recording && !self.savestate_replaying {\n            self.record_savestate_event(&event);\n        }\n        match event {"""
    if old in text and "record_savestate_event" not in text:
        text = text.replace(old, new, 1)
        print("patched input event recording")

    # Insert replay injection immediately before the update in run_frame.
    old = """        if !preload_finished && !may_execute_while_streaming {\n            return;\n        }\n\n        self.update(|context| {"""
    new = """        if !preload_finished && !may_execute_while_streaming {\n            return;\n        }\n\n        if self.savestate_replaying {\n            while self.savestate_input_index < self.savestate_events.len()\n                && self.savestate_events[self.savestate_input_index].frame == self.savestate_frame\n            {\n                let event = self.savestate_events[self.savestate_input_index].event.clone();\n                self.savestate_input_index += 1;\n                self.handle_event(event);\n            }\n        }\n\n        self.update(|context| {"""
    replace_once(path, old, new, "savestate replay event injection")

    # Increment the logical frame after a real frame has completed.
    old = """        self.needs_render = true;\n    }"""
    new = """        self.savestate_frame = self.savestate_frame.saturating_add(1);\n        self.needs_render = true;\n    }"""
    replace_once(path, old, new, "savestate frame counter")

    # Add methods immediately before the event handler.
    marker = "    /// Handle an event sent into the player from the external windowing system\n"
    methods = r'''    fn record_savestate_event(&mut self, event: &PlayerEvent) {
        if let Some(last) = self.savestate_events.last_mut() {
            if last.frame == self.savestate_frame
                && matches!(&last.event, PlayerEvent::MouseMove { .. })
                && matches!(event, PlayerEvent::MouseMove { .. })
            {
                last.event = event.clone();
                return;
            }
        }

        self.savestate_events.push(SavestateEvent {
            frame: self.savestate_frame,
            event: event.clone(),
        });
    }

    pub fn export_savestate_json(&self) -> Result<String, serde_json::Error> {
        let state = Savestate {
            version: 1,
            frame: self.savestate_frame,
            rng_seed: self.rng.initial_seed(),
            events: self.savestate_events.clone(),
        };
        serde_json::to_string(&state)
    }

    pub fn import_savestate_json(&mut self, json: &str) -> Result<u64, String> {
        let state: Savestate = serde_json::from_str(json)
            .map_err(|e| format!("Invalid Ruffle state file: {e}"))?;

        if state.version != 1 {
            return Err(format!("Unsupported Ruffle state version: {}", state.version));
        }
        if state.frame > 20_000_000 {
            return Err("State is too large to replay safely".to_string());
        }
        if state.events.len() > 2_000_000 {
            return Err("State contains too many input events".to_string());
        }
        if state.events.iter().any(|event| event.frame > state.frame) {
            return Err("State contains an event beyond its saved frame".to_string());
        }

        self.savestate_events = state.events;
        self.savestate_input_index = 0;
        self.savestate_frame = 0;
        self.savestate_target_frame = state.frame;
        self.savestate_replaying = state.frame > 0 || !self.savestate_events.is_empty();
        self.savestate_recording = false;

        if let Some(seed) = state.rng_seed {
            self.rng.restore_initial_seed(seed);
        }

        Ok(state.frame)
    }

    pub fn savestate_step(&mut self) -> u64 {
        self.run_frame();
        self.savestate_frame
    }

    pub fn finalize_savestate_import(&mut self) {
        while self.savestate_input_index < self.savestate_events.len()
            && self.savestate_events[self.savestate_input_index].frame <= self.savestate_frame
        {
            let event = self.savestate_events[self.savestate_input_index].event.clone();
            self.savestate_input_index += 1;
            self.handle_event(event);
        }
        self.savestate_replaying = false;
        self.savestate_recording = true;
    }

'''
    if "pub fn export_savestate_json" not in text:
        if marker not in text:
            die("Could not find Player handle_event marker")
        text = text.replace(marker, methods + marker, 1)
        print("patched savestate methods")

    path.write_text(text, encoding="utf-8")


def patch_web_handle() -> None:
    path = ROOT / "web" / "src" / "lib.rs"
    text = path.read_text(encoding="utf-8")

    marker = "    pub fn is_playing(&self) -> bool {"
    if marker not in text:
        die("Could not find RuffleHandle::is_playing")
    if "pub fn savestate_export" in text:
        print("web savestate handle methods already present")
        return

    methods = r'''    /// Export the current Ruffle deterministic-replay state as JSON.
    #[wasm_bindgen]
    pub fn savestate_export(&self) -> Result<String, JsValue> {
        INSTANCES.with(|instances| {
            let instances = instances.borrow();
            let instance = instances
                .get(*self)
                .ok_or_else(|| JsValue::from_str("Ruffle instance no longer exists"))?;
            let core = instance
                .core
                .lock()
                .map_err(|_| JsValue::from_str("Ruffle core lock failed"))?;
            core.export_savestate_json()
                .map_err(|e| JsValue::from_str(&e.to_string()))
        })
    }

    /// Import a deterministic-replay state after the caller has created a fresh player.
    #[wasm_bindgen]
    pub fn savestate_import(&self, json: String) -> Result<u64, JsValue> {
        INSTANCES.with(|instances| {
            let instances = instances.borrow();
            let instance = instances
                .get(*self)
                .ok_or_else(|| JsValue::from_str("Ruffle instance no longer exists"))?;
            let mut core = instance
                .core
                .lock()
                .map_err(|_| JsValue::from_str("Ruffle core lock failed"))?;
            core.import_savestate_json(&json)
                .map_err(|e| JsValue::from_str(&e))
        })
    }

    /// Run one emulated movie frame while reconstructing an imported state.
    #[wasm_bindgen]
    pub fn savestate_step(&self) -> u64 {
        INSTANCES.with(|instances| {
            let instances = instances.borrow();
            let Some(instance) = instances.get(*self) else {
                return 0;
            };
            let Ok(mut core) = instance.core.lock() else {
                return 0;
            };
            core.savestate_step()
        })
    }

    /// Finish an imported replay by applying input events that occurred at the saved frame.
    #[wasm_bindgen]
    pub fn savestate_finalize(&self) {
        INSTANCES.with(|instances| {
            let instances = instances.borrow();
            if let Some(instance) = instances.get(*self) {
                if let Ok(mut core) = instance.core.lock() {
                    core.finalize_savestate_import();
                }
            }
        });
    }

'''
    text = text.replace(marker, methods + marker, 1)
    path.write_text(text, encoding="utf-8")
    print("patched web RuffleHandle savestate API")


def main() -> None:
    patch_dependencies()
    patch_rng()
    patch_events()
    patch_player()
    patch_web_handle()
    print("Ruffle save-state patch applied successfully.")


if __name__ == "__main__":
    main()
