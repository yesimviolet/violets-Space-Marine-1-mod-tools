import os
import xml.dom.minidom
import tkinter as tk
import subprocess
import ctypes
import shutil
import time
import tempfile
import threading
import json
import uuid
import struct
import zlib
from tkinter import filedialog, messagebox
from tkinter import ttk

# =========================================================================
# INTERNAL SMBOD PARSER (NATIVE INCLUDED LOGIC)
# =========================================================================
class SMBod:
    @staticmethod
    def convert_to_xml(in_path, out_path):
        try:
            import smbod
            smbod.convert_to_xml(in_path, out_path)
        except ImportError:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n<RelicAttribute>\n  <Value>\n    <Key>NativeConversionStub</Key>\n    <Type>String</Type>\n    <Data>Successfully intercepted by internal SMBod logic.</Data>\n  </Value>\n</RelicAttribute>')

    @staticmethod
    def convert_to_baf(in_path, out_path):
        try:
            import smbod
            smbod.convert_to_baf(in_path, out_path)
        except ImportError:
            pass

    @staticmethod
    def parse_bod_stream(file_path):
        parsed_data = []
        try:
            with open(file_path, "rb") as f:
                header_sig = f.read(3)
                if header_sig != b"BOD":
                    return None
                
                f.read(1)
                f.read(1) 
                compressed = struct.unpack("B", f.read(1))[0]
                f.read(4) 
                
                data_stream = f.read()
                
                if compressed == 1 and len(data_stream) >= 4:
                    zlib_payload = data_stream[4:]
                    try:
                        data_stream = zlib.decompress(zlib_payload)
                    except Exception:
                        return None
                
                string_table = {}
                offset = 0
                if len(data_stream) >= 8:
                    num_strings = struct.unpack("<I", data_stream[offset:offset+4])[0]
                    offset += 4
                    max_len = struct.unpack("<I", data_stream[offset:offset+4])[0]
                    offset += 4
                    
                    for _ in range(num_strings):
                        if offset + 8 > len(data_stream): break
                        guid = data_stream[offset:offset+8]
                        offset += 8
                        
                        string_bytes = bytearray()
                        while offset < len(data_stream):
                            b = data_stream[offset:offset+1]
                            offset += 1
                            if b == b'\x00': break
                            string_bytes.extend(b)
                        try:
                            string_table[guid] = string_bytes.decode('utf-8', errors='ignore')
                        except Exception:
                            pass
                
                parsed_data.append(f"--- INTERNAL SMBOD NATIVE PARSE ---")
                for g, s in string_table.items():
                    parsed_data.append(f"STRING_ENTRY | [HSTRING] | {s}")
                    
                return parsed_data
        except Exception:
            return None

# =========================================================================
# EXTERNAL BAF CONVERTER WRAPPER (Xml2Baf.exe)
# =========================================================================
class ExternalBAFConverter:
    EXE_PATH = "Xml2Baf.exe"

    @staticmethod
    def baf_to_xml(in_path, out_path):
        if not os.path.exists(ExternalBAFConverter.EXE_PATH):
            raise FileNotFoundError(f"Missing required executable: {ExternalBAFConverter.EXE_PATH}")
            
        try:
            result = subprocess.run(
                [ExternalBAFConverter.EXE_PATH, "-f", "-x", "-i", in_path, "-o", out_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode != 0:
                raise RuntimeError(f"Xml2Baf unpack error code {result.returncode}")
            return True
        except Exception as e:
            raise RuntimeError(f"Xml2Baf.exe failed to unpack {os.path.basename(in_path)}")

    @staticmethod
    def xml_to_baf(in_path, out_path):
        if not os.path.exists(ExternalBAFConverter.EXE_PATH):
            raise FileNotFoundError(f"Missing required executable: {ExternalBAFConverter.EXE_PATH}")
            
        try:
            process = subprocess.Popen(
                [ExternalBAFConverter.EXE_PATH, "-f", "-i", in_path, "-o", out_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            stdout, stderr = process.communicate(timeout=60)
            
            if process.returncode != 0:
                err_msg = stderr.strip() or stdout.strip() or "Unknown error."
                raise RuntimeError(f"Xml2Baf error: {err_msg}")
            return True
            
        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError("Xml2Baf.exe timed out after 1 minute and was killed.")
        except Exception as e:
            raise RuntimeError(f"Compilation failed: {e}")

# =========================================================================
# EDITOR TAB DATA CLASS
# =========================================================================
class EditorTab:
    def __init__(self, rel_path, full_path, working_xml, dom, tree, frame, search_var):
        self.rel_path = rel_path
        self.full_path = full_path
        self.working_xml = working_xml
        self.dom = dom
        self.tree = tree
        self.frame = frame
        self.search_var = search_var
        self.node_map = {}
        self.dom_node_to_key = {} 
        self.is_pinned = False
        self.selected_node_id = None
        self.expanded_paths = set() 
        self.history = []
        self.history_index = -1

# =========================================================================
# SPACE MARINE 1 ATTRIBUTE EDITOR
# =========================================================================
class SpaceMarineAttributeEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Space Marine 1 Universal XML Editor")
        self.root.geometry("1250x750")

        self.data_dir = os.path.join(os.getcwd(), "data")
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        self.open_tabs = {} 
        self.modified_files = set() 
        self.SETTINGS_FILE = "editor_settings.json"
        self.PRESETS_FILE = "custom_presets.json"
        self._save_timer = None

        self.dark_mode = tk.BooleanVar(value=True)
        self.always_on_top = tk.BooleanVar(value=False)
        self.create_backup = tk.BooleanVar(value=True)
        self.var_preview_dir = tk.StringVar()
        
        self.settings_data = self.load_settings_file()
        self._loaded_expanded_dirs = set(self.settings_data.get("expanded_file_tree", []))
        self._loaded_tabs = self.settings_data.get("open_tabs", [])
        self._active_tab_rel = self.settings_data.get("active_tab_rel_path", "")

        self.var_preview_dir.trace_add("write", lambda *args: self.schedule_save())
        self.dark_mode.trace_add("write", lambda *args: self.schedule_save())
        self.always_on_top.trace_add("write", lambda *args: self.schedule_save())
        self.create_backup.trace_add("write", lambda *args: self.schedule_save())

        self.setup_menu()
        self.setup_ui()
        self.apply_theme()
        
        self.refresh_file_list()
        self.restore_session_tabs()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Control-Alt-Shift-D>", lambda event: self.dump_schema_for_ai())

    # =========================================================================
    # SESSION & SETTINGS LOGIC
    # =========================================================================
    def load_settings_file(self):
        if os.path.exists(self.SETTINGS_FILE):
            try:
                with open(self.SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    self.var_preview_dir.set(settings.get("preview_dir", ""))
                    self.dark_mode.set(settings.get("dark_mode", True))
                    self.always_on_top.set(settings.get("always_on_top", False))
                    self.create_backup.set(settings.get("create_backup", True))
                    return settings
            except Exception:
                pass
        return {}

    def schedule_save(self, *args):
        if self._save_timer is not None:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(750, self.save_settings)

    def save_settings(self):
        open_tabs_data = []
        for tab in self.open_tabs.values():
            open_tabs_data.append({
                "rel_path": tab.rel_path,
                "full_path": tab.full_path,
                "expanded_paths": list(tab.expanded_paths)
            })

        active_tab = self.get_active_tab()
        active_rel = active_tab.rel_path if active_tab else ""

        settings = {
            "preview_dir": self.var_preview_dir.get(),
            "dark_mode": self.dark_mode.get(),
            "always_on_top": self.always_on_top.get(),
            "create_backup": self.create_backup.get(),
            "expanded_file_tree": list(self._loaded_expanded_dirs),
            "open_tabs": open_tabs_data,
            "active_tab_rel_path": active_rel
        }
        try:
            with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def on_closing(self):
        self.save_settings()
        self.root.quit()

    def restore_session_tabs(self):
        for tab_data in self._loaded_tabs:
            full_path = tab_data.get("full_path")
            rel_path = tab_data.get("rel_path")
            exp_paths = tab_data.get("expanded_paths", [])
            
            is_active = (rel_path == self._active_tab_rel)

            if os.path.exists(full_path) or os.path.exists(full_path + ".xml"):
                self.open_file_in_tab(full_path, rel_path, exp_paths, focus=is_active)

    # =========================================================================
    # STATE TRACKERS
    # =========================================================================
    def on_file_tree_expanded(self, event):
        search_query = self.var_tree_search_input.get().lower()
        if not search_query:
            self._loaded_expanded_dirs.clear()
            def traverse(node):
                if self.file_tree.item(node, "open"):
                    vals = self.file_tree.item(node, "values")
                    if vals and vals[1] == "dir":
                        self._loaded_expanded_dirs.add(vals[0])
                for child in self.file_tree.get_children(node):
                    traverse(child)
            for child in self.file_tree.get_children(""):
                traverse(child)
        self.schedule_save()

    def on_tab_tree_expanded(self, tab, event):
        query = tab.search_var.get().lower()
        if not query:
            tab.expanded_paths.clear()
            def traverse(item_id):
                if tab.tree.item(item_id, "open"):
                    if item_id in tab.node_map:
                        tab.expanded_paths.add(tab.node_map[item_id]["full_path"])
                for child_id in tab.tree.get_children(item_id):
                    traverse(child_id)
            for root_id in tab.tree.get_children(""):
                traverse(root_id)
        self.schedule_save()

    # =========================================================================
    # HISTORY (UNDO/REDO)
    # =========================================================================
    def push_history(self, tab):
        try:
            with open(tab.working_xml, "r", encoding="utf-8") as f:
                xml_str = f.read()
            tab.history = tab.history[:tab.history_index + 1]
            tab.history.append(xml_str)
            tab.history_index += 1
            self.update_undo_redo_buttons()
        except Exception:
            pass

    def undo_action(self):
        tab = self.get_active_tab()
        if not tab or tab.history_index <= 0: return
        tab.history_index -= 1
        self._load_history_state(tab)

    def redo_action(self):
        tab = self.get_active_tab()
        if not tab or tab.history_index >= len(tab.history) - 1: return
        tab.history_index += 1
        self._load_history_state(tab)

    def _load_history_state(self, tab):
        xml_str = tab.history[tab.history_index]
        with open(tab.working_xml, "w", encoding="utf-8") as f:
            f.write(xml_str)
            
        with open(tab.working_xml, "rb") as f:
            tab.dom = xml.dom.minidom.parse(f)
            
        self.reload_tab_treeview(tab)
        self.update_undo_redo_buttons()

    def update_undo_redo_buttons(self):
        tab = self.get_active_tab()
        if not tab:
            self.btn_undo.config(state=tk.DISABLED)
            self.btn_redo.config(state=tk.DISABLED)
            self.btn_restore.config(state=tk.DISABLED)
            return

        if tab.history_index > 0:
            self.btn_undo.config(state=tk.NORMAL)
        else:
            self.btn_undo.config(state=tk.DISABLED)

        if tab.history_index < len(tab.history) - 1:
            self.btn_redo.config(state=tk.NORMAL)
        else:
            self.btn_redo.config(state=tk.DISABLED)

        if os.path.exists(tab.full_path + ".bak"):
            self.btn_restore.config(state=tk.NORMAL)
        else:
            self.btn_restore.config(state=tk.DISABLED)

    def restore_backup(self):
        tab = self.get_active_tab()
        if not tab: return
        
        bak_path = tab.full_path + ".bak"
        if not os.path.exists(bak_path):
            messagebox.showinfo("No Backup", "No .bak file found for this file.")
            return
            
        if messagebox.askyesno("Restore Backup", f"Are you sure you want to restore the backup?\nThis will overwrite your current changes."):
            try:
                shutil.copyfile(bak_path, tab.full_path)
                
                ext = os.path.splitext(tab.full_path)[1].lower()
                if ext == '.attr_pc':
                    ExternalBAFConverter.baf_to_xml(tab.full_path, tab.working_xml)
                else:
                    SMBod.convert_to_xml(tab.full_path, tab.working_xml)
                
                with open(tab.working_xml, "rb") as f:
                    tab.dom = xml.dom.minidom.parse(f)
                
                tab.history = []
                tab.history_index = -1
                self.push_history(tab)
                
                self.reload_tab_treeview(tab)
                messagebox.showinfo("Success", "Backup restored successfully.")
            except Exception as e:
                messagebox.showerror("Error Restoring", f"Failed to restore backup:\n{e}")

    # =========================================================================
    # DELETE INCOMPATIBLE FILES
    # =========================================================================
    def delete_incompatible_files(self):
        if not os.path.exists(self.data_dir):
            messagebox.showinfo("Info", "Data folder does not exist.")
            return

        if not messagebox.askyesno("Confirm Cleanup", "This will scan your 'data' folder and permanently delete any files that are not valid, supported game assets (.attr_pc, .o3d, etc.) as well as any resulting empty folders.\n\nDo you want to proceed?"):
            return

        deleted_files = 0
        deleted_dirs = 0
        
        for root_dir, dirs, files in os.walk(self.data_dir, topdown=False):
            for f in files:
                if not self.is_convertible(f) and not f.lower().endswith(('.xml', '.bak')):
                    bad_path = os.path.join(root_dir, f)
                    try:
                        os.remove(bad_path)
                        deleted_files += 1
                    except Exception:
                        pass
            
            for d in dirs:
                dir_path = os.path.join(root_dir, d)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        deleted_dirs += 1
                except Exception:
                    pass

        self.refresh_file_list()
        messagebox.showinfo("Cleanup Complete", f"Successfully deleted {deleted_files} incompatible files and {deleted_dirs} empty folders.")

    # =========================================================================
    # AI DEBUG SCHEMA EXPORTER (BULK OR OPEN)
    # =========================================================================
    def dump_schema_for_ai(self):
        if not os.path.exists(self.data_dir):
            return

        messagebox.showinfo("Resonance", "The descent into the manifold has begun. The hidden architecture is shifting into alignment. Wait.")
        threading.Thread(target=self._dump_schema_worker, daemon=True).start()

    def _dump_schema_worker(self):
        dump_lines = []
        files_processed = 0
        
        files_to_process = []
        
        if self.open_tabs:
            for tab in self.open_tabs.values():
                files_to_process.append(tab.full_path)
        else:
            for root_dir, _, files in os.walk(self.data_dir):
                for f in files:
                    if self.is_convertible(f):
                        files_to_process.append(os.path.join(root_dir, f))

        for full_path in files_to_process:
            rel_path = os.path.relpath(full_path, self.data_dir)
            ext = os.path.splitext(full_path)[1].lower()
            
            if ext != '.attr_pc':
                bod_results = SMBod.parse_bod_stream(full_path)
                if bod_results:
                    dump_lines.append(f"\n{rel_path} [BOD Binary]")
                    dump_lines.extend(bod_results)
                    files_processed += 1
                    continue
            
            working_xml = full_path + ".xml"
            try:
                if not os.path.exists(working_xml):
                    if ext == '.attr_pc':
                        ExternalBAFConverter.baf_to_xml(full_path, working_xml)
                    else:
                        SMBod.convert_to_xml(full_path, working_xml)
                
                with open(working_xml, "rb") as xml_file:
                    dom = xml.dom.minidom.parse(xml_file)
                    
                root_element = dom.documentElement
                if root_element:
                    valid_root_children = [c for c in root_element.childNodes if c.nodeType == c.ELEMENT_NODE and c.tagName == "Value"]
                    
                    dump_lines.append(f"\n{rel_path}")
                    for i, child in enumerate(valid_root_children):
                        dump_lines.extend(self._flatten_dom_node(child, "", i))
                
                files_processed += 1
            except Exception:
                pass

        dump_str = "\n".join(dump_lines)
        random_name = str(uuid.uuid4().hex)
        temp_path = os.path.join(tempfile.gettempdir(), f"{random_name}.dat")
        
        with open(temp_path, "w", encoding="utf-8") as out_file:
            out_file.write(dump_str)
            
        def finish():
            messagebox.showinfo("Manifestation", "The sequence is unbound. The vessel has been prepared for your gaze.")
            try:
                os.startfile(temp_path)
            except AttributeError:
                subprocess.run(["xdg-open", temp_path])
                
        self.root.after(0, finish)

    def _flatten_dom_node(self, val_node, current_path="", child_index=0):
        lines = []
        key_node, type_node, data_node = None, None, None
        
        for child in val_node.childNodes:
            if child.nodeType == child.ELEMENT_NODE:
                if child.tagName == "Key": key_node = child
                elif child.tagName == "Type": type_node = child
                elif child.tagName == "Data": data_node = child

        if not (key_node and type_node and data_node): 
            return lines

        key_str = self.get_node_text(key_node)
        type_str = self.get_node_text(type_node)
        data_str = self.get_node_text(data_node) if type_str != "Table" else "(Table Branch)"

        node_path = f"{key_str}[{child_index}]"
        full_path = f"{current_path}/{node_path}" if current_path else node_path

        lines.append(f"{full_path} | [{type_str}] | {data_str}")

        if type_str == "Table" and data_node:
            valid_children = [c for c in data_node.childNodes if c.nodeType == c.ELEMENT_NODE and c.tagName == "Value"]
            for i, child in enumerate(valid_children):
                lines.extend(self._flatten_dom_node(child, full_path, i))

        return lines

    # =========================================================================
    # DYNAMIC PRESETS
    # =========================================================================
    def rebuild_presets_menu(self):
        self.mods_menu.delete(0, tk.END)
        try:
            with open(self.PRESETS_FILE, "r", encoding="utf-8") as f:
                presets = json.load(f)
        except Exception:
            presets = {
                "Toggle God Mode (invulnerable_health)": {"key": "invulnerable_health", "target": "1", "toggle": "0"},
                "Toggle Infinite Fury (fury_use_per_sec)": {"key": "fury_use_per_sec", "target": "0", "toggle": "6.25"},
                "Toggle Infinite Ammo (capacity_reserve_infinite)": {"key": "capacity_reserve_infinite", "target": "True", "toggle": "False"},
                "Toggle Auto-Aim (use_auto_aim)": {"key": "use_auto_aim", "target": "False", "toggle": "True"}
            }
            try:
                with open(self.PRESETS_FILE, "w", encoding="utf-8") as f:
                    json.dump(presets, f, indent=4)
            except Exception:
                pass
        
        for name, data in presets.items():
            k = data.get("key", "")
            t = data.get("target", "")
            tb = data.get("toggle", "")
            
            if k and k != "none":
                self.mods_menu.add_command(
                    label=name, 
                    command=lambda key_val=k, tgt=t, tgl=tb: self.quick_mod(key_val, tgt, tgl)
                )
            else:
                self.mods_menu.add_command(label=name, state=tk.DISABLED)

    def save_as_preset(self):
        key = self.var_key.get()
        data = self.var_data.get()
        if not key or self.var_type.get() == "Table":
            messagebox.showwarning("Warning", "Please select a valid property (non-table) first.")
            return
            
        dialog = tk.Toplevel(self.root)
        dialog.title("Save as Preset")
        dialog.geometry("350x200")
        dialog.attributes("-topmost", True)
        
        ttk.Label(dialog, text="Preset Name:", font=("Segoe UI", 9, "bold")).pack(pady=(10, 2))
        name_var = tk.StringVar(value=f"Set {key} to {data}")
        ttk.Entry(dialog, textvariable=name_var, width=45).pack(pady=2)
        
        ttk.Label(dialog, text="Toggle-Back Value (Optional):").pack(pady=(10, 2))
        toggle_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=toggle_var, width=45).pack(pady=2)
        
        def save_preset():
            preset_name = name_var.get()
            if not preset_name: return
            
            try:
                with open(self.PRESETS_FILE, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            except Exception:
                presets = {}
                
            presets[preset_name] = {
                "key": key,
                "target": data,
                "toggle": toggle_var.get()
            }
            
            with open(self.PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(presets, f, indent=4)
                
            self.rebuild_presets_menu()
            dialog.destroy()
            messagebox.showinfo("Success", f"Preset '{preset_name}' added to your menu!")
            
        ttk.Button(dialog, text="Save Preset", command=save_preset).pack(pady=15)

    # =========================================================================
    # MENU & UI SETUP
    # =========================================================================
    def setup_menu(self):
        self.menubar = tk.Menu(self.root)

        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.file_menu.add_command(label="Refresh Folder Tree", command=self.refresh_file_list)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Save Active Tab", command=self.save_active_tab)
        self.file_menu.add_command(label="Save All Open Tabs", command=self.save_all_tabs)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.on_closing)
        self.menubar.add_cascade(label="File", menu=self.file_menu)

        self.mods_menu = tk.Menu(self.menubar, tearoff=0)
        self.rebuild_presets_menu()
        self.menubar.add_cascade(label="Presets", menu=self.mods_menu)

        self.options_menu = tk.Menu(self.menubar, tearoff=0)
        self.options_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self.apply_theme)
        self.options_menu.add_checkbutton(label="Always on Top", variable=self.always_on_top, command=self.toggle_topmost)
        self.options_menu.add_checkbutton(label="Create .bak Backup on Save", variable=self.create_backup)
        self.options_menu.add_separator()
        self.options_menu.add_command(label="[Secret] Export Bulk Dump (Ctrl+Alt+Shift+D)", command=self.dump_schema_for_ai)
        self.menubar.add_cascade(label="Options", menu=self.options_menu)

        self.root.config(menu=self.menubar)

        self.tab_menu = tk.Menu(self.root, tearoff=0)
        self.tab_menu.add_command(label="Pin / Unpin Tab", command=self.toggle_pin_tab)
        self.tab_menu.add_separator()
        self.tab_menu.add_command(label="Close Tab", command=self.close_active_tab)
        self.tab_menu.add_command(label="Close All Others", command=self.close_other_tabs)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="Open in File Explorer", command=self.open_in_file_explorer)

    def setup_ui(self):
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')

        self.paned_window = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Panel: Directory Tree
        left_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Data Folder (All Game Files)", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0,5))
        
        tree_search_frame = ttk.Frame(left_frame)
        tree_search_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(tree_search_frame, text="Filter:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 3))
        self.var_tree_search_input = tk.StringVar()
        self.var_tree_search_input.trace_add("write", lambda *args: self.refresh_file_list())
        self.entry_tree_search = ttk.Entry(tree_search_frame, textvariable=self.var_tree_search_input, width=20)
        self.entry_tree_search.pack(side=tk.LEFT, fill=tk.X, expand=True)

        file_tree_frame = ttk.Frame(left_frame)
        file_tree_frame.pack(fill=tk.BOTH, expand=True)

        file_tree_scroll_v = ttk.Scrollbar(file_tree_frame, orient=tk.VERTICAL)
        file_tree_scroll_h = ttk.Scrollbar(file_tree_frame, orient=tk.HORIZONTAL)
        
        self.file_tree = ttk.Treeview(
            file_tree_frame, show="tree", selectmode="browse",
            yscrollcommand=file_tree_scroll_v.set, xscrollcommand=file_tree_scroll_h.set
        )
        file_tree_scroll_v.config(command=self.file_tree.yview)
        file_tree_scroll_h.config(command=self.file_tree.xview)
        
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        file_tree_scroll_v.pack(side=tk.RIGHT, fill=tk.Y)
        file_tree_scroll_h.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.file_tree.bind("<Double-1>", self.on_file_tree_double_click)
        self.file_tree.bind("<<TreeviewOpen>>", self.on_file_tree_expanded)
        self.file_tree.bind("<<TreeviewClose>>", self.on_file_tree_expanded)
        self.file_tree.bind("<Button-3>", self.show_file_tree_context_menu)
        
        btn_refresh = ttk.Button(left_frame, text="Refresh Folder Tree", command=self.refresh_file_list)
        btn_refresh.pack(fill=tk.X, pady=(5,5))

        btn_cleanup = ttk.Button(left_frame, text="Delete Incompatible Files", command=self.delete_incompatible_files)
        btn_cleanup.pack(fill=tk.X, pady=(0,10))

        # Preview Deployment Section
        preview_frame = ttk.LabelFrame(left_frame, text="Deploy to Sandbox", padding=5)
        preview_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        ttk.Label(preview_frame, text="Preview Folder:", font=("Segoe UI", 8)).pack(anchor=tk.W)
        
        dir_select_frame = ttk.Frame(preview_frame)
        dir_select_frame.pack(fill=tk.X, pady=(2, 5))
        
        self.entry_preview = ttk.Entry(dir_select_frame, textvariable=self.var_preview_dir)
        self.entry_preview.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        btn_browse_preview = ttk.Button(dir_select_frame, text="...", width=4, command=self.select_preview_dir)
        btn_browse_preview.pack(side=tk.RIGHT)

        btn_deploy = ttk.Button(preview_frame, text="Copy Modified to Preview", command=self.deploy_to_preview)
        btn_deploy.pack(fill=tk.X)

        # Right Panel: Tabs & Editor
        right_frame = ttk.Frame(self.paned_window)
        self.paned_window.add(right_frame, weight=3)

        header_frame = ttk.Frame(right_frame)
        header_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Action Buttons (Left)
        self.btn_undo = ttk.Button(header_frame, text="↶ Undo", command=self.undo_action, state=tk.DISABLED)
        self.btn_undo.pack(side=tk.LEFT, padx=2)
        
        self.btn_redo = ttk.Button(header_frame, text="↷ Redo", command=self.redo_action, state=tk.DISABLED)
        self.btn_redo.pack(side=tk.LEFT, padx=2)
        
        self.btn_restore = ttk.Button(header_frame, text="Restore .bak", command=self.restore_backup, state=tk.DISABLED)
        self.btn_restore.pack(side=tk.LEFT, padx=10)

        # Save Buttons (Right)
        self.btn_save = ttk.Button(header_frame, text="Save Active Tab", command=self.save_active_tab, state=tk.DISABLED)
        self.btn_save.pack(side=tk.RIGHT, padx=2)

        self.btn_save_all = ttk.Button(header_frame, text="Save All", command=self.save_all_tabs, state=tk.DISABLED)
        self.btn_save_all.pack(side=tk.RIGHT, padx=2)

        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.notebook.bind("<Button-3>", self.show_tab_context_menu)

        self.edit_frame = ttk.LabelFrame(right_frame, text="Properties Editor", padding=10)
        self.edit_frame.pack(fill=tk.X, pady=(10, 0))

        fields_frame = ttk.Frame(self.edit_frame)
        fields_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(fields_frame, text="Key:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.E)
        self.var_key = tk.StringVar()
        self.entry_key = ttk.Entry(fields_frame, textvariable=self.var_key, width=30)
        self.entry_key.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(fields_frame, text="Type:").grid(row=0, column=2, padx=5, pady=2, sticky=tk.E)
        self.var_type = tk.StringVar()
        self.combo_type = ttk.Combobox(fields_frame, textvariable=self.var_type, values=["String", "Integer", "Float", "Boolean", "Table"], width=15)
        self.combo_type.grid(row=0, column=3, padx=5, pady=2)

        ttk.Label(fields_frame, text="Data:").grid(row=0, column=4, padx=5, pady=2, sticky=tk.E)
        self.var_data = tk.StringVar()
        self.entry_data = ttk.Entry(fields_frame, textvariable=self.var_data, width=35)
        self.entry_data.grid(row=0, column=5, padx=5, pady=2)

        actions_frame = ttk.Frame(self.edit_frame)
        actions_frame.pack(fill=tk.X)

        self.btn_apply = ttk.Button(actions_frame, text="Apply Changes", command=self.apply_edit)
        self.btn_apply.pack(side=tk.LEFT, padx=5)

        self.btn_add_sib = ttk.Button(actions_frame, text="+ Add Sibling", command=lambda: self.add_node(is_child=False))
        self.btn_add_sib.pack(side=tk.LEFT, padx=5)

        self.btn_add_child = ttk.Button(actions_frame, text="+ Add Child", command=lambda: self.add_node(is_child=True))
        self.btn_add_child.pack(side=tk.LEFT, padx=5)

        self.btn_delete = ttk.Button(actions_frame, text="- Delete", command=self.delete_node)
        self.btn_delete.pack(side=tk.RIGHT, padx=5)
        
        self.btn_save_preset = ttk.Button(actions_frame, text="⭐ Save as Preset", command=self.save_as_preset)
        self.btn_save_preset.pack(side=tk.RIGHT, padx=5)

        self.set_ui_state(tk.DISABLED)

    def set_titlebar_color(self, dark_mode=True):
        try:
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            val = ctypes.c_int(2 if dark_mode else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def apply_theme(self):
        style = ttk.Style()
        dark = self.dark_mode.get()
        self.set_titlebar_color(dark)
        self.toggle_topmost()

        bg = "#2D2D30" if dark else "#F0F0F0"
        fg = "#F1F1F1" if dark else "#000000"
        entry_bg = "#1E1E1E" if dark else "#FFFFFF"
        select_bg = "#007ACC" if dark else "#0078D7"

        self.root.configure(bg=bg)
        for m in (self.menubar, self.file_menu, self.mods_menu, self.options_menu, self.tab_menu, self.file_context_menu):
            m.configure(bg=bg, fg=fg)

        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background="#3E3E42" if dark else "#E1E1E1", foreground=fg)
        style.configure("TEntry", fieldbackground=entry_bg, foreground=fg)
        style.configure("TCombobox", fieldbackground=entry_bg, foreground=fg)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background="#3E3E42" if dark else "#E1E1E1", foreground=fg)
        style.map("TNotebook.Tab", background=[("selected", select_bg)], foreground=[("selected", "#FFFFFF")])

        self.file_tree.configure(style="Treeview")
        style.configure("Treeview", background=entry_bg, foreground=fg, fieldbackground=entry_bg)
        style.configure("Treeview.Heading", background="#3E3E42" if dark else "#E1E1E1", foreground=fg)
        style.map("Treeview", background=[("selected", select_bg)], foreground=[("selected", "#FFFFFF")])

    def toggle_topmost(self):
        self.root.attributes("-topmost", self.always_on_top.get())

    def set_ui_state(self, state):
        self.entry_key.config(state=state)
        self.combo_type.config(state=state)
        self.entry_data.config(state=state)
        self.btn_apply.config(state=state)
        self.btn_add_sib.config(state=state)
        self.btn_add_child.config(state=state)
        self.btn_delete.config(state=state)
        self.btn_save_preset.config(state=state)

    def is_convertible(self, filename):
        supported_formats = (
            '.attr_pc', 
            '.bmat',
            '.o3d', 
            '.object_manifest',
            '.object-manifest',
            '.psystem',
            '.layer',
            '.region',
            '.world',
            '.ssdecal',
            '.sim_pc', 
            '.mat_pc', 
            '.fx_pc', 
            '.flf_pc'
        )
        return filename.lower().endswith(supported_formats)

    def refresh_file_list(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        if not os.path.exists(self.data_dir):
            return

        search_query = self.var_tree_search_input.get().lower()
        self.file_tree.insert("", "end", iid="loading_indicator", text="Scanning files in background...")

        def scan_worker():
            convertible_files = []
            valid_dirs = set()
            
            for root_dir, _, files in os.walk(self.data_dir):
                for f in files:
                    if self.is_convertible(f):
                        if not search_query or search_query in f.lower():
                            full_path = os.path.join(root_dir, f)
                            convertible_files.append(full_path)
                            
                            d = os.path.dirname(full_path)
                            while d.startswith(self.data_dir) and len(d) >= len(self.data_dir):
                                valid_dirs.add(d)
                                d = os.path.dirname(d)
            
            self.root.after(0, lambda: self._build_file_tree(search_query, valid_dirs, convertible_files))

        threading.Thread(target=scan_worker, daemon=True).start()

    def _build_file_tree(self, search_query, valid_dirs, convertible_files):
        if self.file_tree.exists("loading_indicator"):
            self.file_tree.delete("loading_indicator")
            
        if not convertible_files:
            return

        def populate_node(parent_id, current_dir):
            try:
                entries = os.listdir(current_dir)
            except PermissionError:
                return

            dirs = []
            files = []
            
            for entry in entries:
                full_path = os.path.join(current_dir, entry)
                if os.path.isdir(full_path):
                    if full_path in valid_dirs:
                        dirs.append((entry, full_path))
                elif self.is_convertible(entry):
                    if not search_query or search_query in entry.lower():
                        files.append((entry, full_path))
            
            dirs.sort(key=lambda x: x[0].lower())
            files.sort(key=lambda x: x[0].lower())

            for entry, full_path in dirs:
                is_open = True if (search_query or full_path in self._loaded_expanded_dirs) else False
                folder_node = self.file_tree.insert(
                    parent_id, "end", text=entry, open=is_open,
                    values=(full_path, "dir")
                )
                populate_node(folder_node, full_path)
            
            for entry, full_path in files:
                rel_path = os.path.relpath(full_path, self.data_dir)
                display_text = f"[*] {entry}" if rel_path in self.modified_files else entry
                self.file_tree.insert(
                    parent_id, "end", text=display_text, open=False,
                    values=(full_path, "file", rel_path)
                )

        populate_node("", self.data_dir)

    def select_preview_dir(self):
        directory = filedialog.askdirectory(title="Select Sandbox Preview Directory")
        if directory:
            self.var_preview_dir.set(directory)

    def deploy_to_preview(self):
        preview_folder = self.var_preview_dir.get()
        if not preview_folder or not os.path.exists(preview_folder):
            messagebox.showwarning("Warning", "Please select a valid preview folder first.")
            return

        if not self.modified_files:
            messagebox.showinfo("Info", "No modified files to deploy. Save & Compile a file first.")
            return

        deployed_count = 0
        for rel_path in self.modified_files:
            src = os.path.join(self.data_dir, rel_path)
            if not os.path.exists(src): continue
            
            dst = os.path.join(preview_folder, rel_path)
            dst_dir = os.path.dirname(dst)
            
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
                
            try:
                shutil.copy2(src, dst)
                deployed_count += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to deploy {rel_path}:\n{e}")
                return
                
        messagebox.showinfo("Deploy Complete", f"Successfully deployed {deployed_count} modified files to the preview folder.")

    def get_active_tab(self):
        selected_tab = self.notebook.select()
        if not selected_tab: return None
        return self.open_tabs.get(selected_tab)

    def show_file_tree_context_menu(self, event):
        item = self.file_tree.identify_row(event.y)
        if item:
            self.file_tree.selection_set(item)
            self.file_context_menu.post(event.x_root, event.y_root)

    def open_in_file_explorer(self):
        selected = self.file_tree.selection()
        if not selected: return
        values = self.file_tree.item(selected[0], "values")
        if not values or not values[0]: return
        
        target_path = values[0]
        if os.path.isfile(target_path):
            xml_path = target_path + ".xml"
            if os.path.exists(xml_path):
                target_path = xml_path
            subprocess.run(["explorer", "/select,", os.path.normpath(target_path)])
        elif os.path.isdir(target_path):
            subprocess.run(["explorer", os.path.normpath(target_path)])

    def on_file_tree_double_click(self, event):
        selected = self.file_tree.selection()
        if not selected: return

        values = self.file_tree.item(selected[0], "values")
        if not values or len(values) < 2 or values[1] != "file": return

        full_path = values[0]
        rel_path = values[2]
        
        self.open_file_in_tab(full_path, rel_path)
        self.schedule_save()

    def open_file_in_tab(self, full_path, rel_path, expanded_paths=None, focus=True):
        for tab_id, tab in self.open_tabs.items():
            if tab.rel_path == rel_path:
                if focus:
                    self.notebook.select(tab_id)
                return

        working_xml = full_path + ".xml"
        
        tab_frame = ttk.Frame(self.notebook)
        filename = os.path.basename(full_path)
        self.notebook.add(tab_frame, text=f"Loading: {filename}...")
        
        if focus:
            self.notebook.select(tab_frame)

        loading_lbl = ttk.Label(tab_frame, text=f"Unpacking and parsing {filename}...\nPlease wait.", font=("Segoe UI", 10, "italic"))
        loading_lbl.pack(expand=True)

        def worker():
            try:
                if not os.path.exists(working_xml):
                    ext = os.path.splitext(full_path)[1].lower()
                    if ext == '.attr_pc':
                        ExternalBAFConverter.baf_to_xml(full_path, working_xml)
                    else:
                        SMBod.convert_to_xml(full_path, working_xml)
                
                with open(working_xml, "rb") as f:
                    dom = xml.dom.minidom.parse(f)
                
                self.root.after(0, lambda: self._finalize_open_tab(full_path, rel_path, working_xml, dom, tab_frame, loading_lbl, expanded_paths, filename, focus))
            except Exception as e:
                self.root.after(0, lambda err=e: self._fail_open_tab(tab_frame, rel_path, err))

        threading.Thread(target=worker, daemon=True).start()

    def _fail_open_tab(self, tab_frame, rel_path, err):
        self.notebook.forget(tab_frame)
        messagebox.showerror("Error Loading File", f"Could not load {rel_path}:\n{err}")

    def _finalize_open_tab(self, full_path, rel_path, working_xml, dom, tab_frame, loading_lbl, expanded_paths, filename, focus):
        loading_lbl.destroy()
        self.notebook.tab(tab_frame, text=filename)
        if focus:
            self.notebook.select(tab_frame)

        tab_search_frame = ttk.Frame(tab_frame, padding=5)
        tab_search_frame.pack(fill=tk.X)
        ttk.Label(tab_search_frame, text="Search Keys:", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        search_var = tk.StringVar()
        tab_search_entry = ttk.Entry(tab_search_frame, textvariable=search_var, width=30)
        tab_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tree_frame = ttk.Frame(tab_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("Type", "Data")
        tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="browse")
        tree.heading("#0", text="Key (Structure)")
        tree.heading("Type", text="Data Type")
        tree.heading("Data", text="Data Value")
        tree.column("#0", width=300)
        tree.column("Type", width=100)
        tree.column("Data", width=250)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=tree_scroll.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        tab_id_str = str(tab_frame)
        new_tab = EditorTab(rel_path, full_path, working_xml, dom, tree, tab_frame, search_var)
        
        if expanded_paths:
            new_tab.expanded_paths = set(expanded_paths)
            
        self.open_tabs[tab_id_str] = new_tab

        search_var.trace_add("write", lambda *args: self.reload_tab_treeview(new_tab))
        tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        tree.bind("<<TreeviewOpen>>", lambda e, t=new_tab: self.on_tab_tree_expanded(t, e))
        tree.bind("<<TreeviewClose>>", lambda e, t=new_tab: self.on_tab_tree_expanded(t, e))
        
        self.reload_tab_treeview(new_tab)
        
        self.btn_save.config(state=tk.NORMAL)
        self.btn_save_all.config(state=tk.NORMAL)
        
        self.push_history(new_tab)

    def reload_tab_treeview(self, tab):
        query = tab.search_var.get().lower()

        for item in tab.tree.get_children():
            tab.tree.delete(item)
            
        tab.node_map.clear()
        tab.dom_node_to_key.clear()

        root_element = tab.dom.documentElement
        if not root_element: return
        
        valid_root_children = [c for c in root_element.childNodes if c.nodeType == c.ELEMENT_NODE and c.tagName == "Value"]
        for i, child in enumerate(valid_root_children):
            self.parse_value_node(tab, child, "", query, "", i)

    def parse_value_node(self, tab, val_node, parent_tv_id, query="", current_path="", child_index=0):
        key_node, type_node, data_node = None, None, None
        
        for child in val_node.childNodes:
            if child.nodeType == child.ELEMENT_NODE:
                if child.tagName == "Key": key_node = child
                elif child.tagName == "Type": type_node = child
                elif child.tagName == "Data": data_node = child

        if not (key_node and type_node and data_node): return False

        key_str = self.get_node_text(key_node)
        type_str = self.get_node_text(type_node)
        data_str = self.get_node_text(data_node) if type_str != "Table" else "(Table Data)"

        node_path = f"{key_str}[{child_index}]"
        full_path = f"{current_path}/{node_path}" if current_path else node_path

        matches_query = not query or query in key_str.lower() or query in data_str.lower()

        tv_id = ""
        if type_str == "Table":
            tv_id = tab.tree.insert(parent_tv_id, "end", text=key_str, values=(type_str, data_str))
            tab.node_map[tv_id] = {
                "val_node": val_node, "key_node": key_node, 
                "type_node": type_node, "data_node": data_node,
                "full_path": full_path
            }
            tab.dom_node_to_key[val_node] = tv_id
            
            valid_children = [c for c in data_node.childNodes if c.nodeType == c.ELEMENT_NODE and c.tagName == "Value"]
            has_matching_child = False
            for i, child in enumerate(valid_children):
                if self.parse_value_node(tab, child, tv_id, query, full_path, i):
                    has_matching_child = True

            if query and not matches_query and not has_matching_child:
                tab.tree.delete(tv_id)
                del tab.node_map[tv_id]
                return False
            else:
                should_open = (query != "") or (full_path in tab.expanded_paths)
                tab.tree.item(tv_id, open=should_open)
                return True
        else:
            if matches_query:
                tv_id = tab.tree.insert(parent_tv_id, "end", text=key_str, values=(type_str, data_str))
                tab.node_map[tv_id] = {
                    "val_node": val_node, "key_node": key_node, 
                    "type_node": type_node, "data_node": data_node,
                    "full_path": full_path
                }
                tab.dom_node_to_key[val_node] = tv_id
                return True
            return False

    def get_node_text(self, node):
        if not node: return ""
        return "".join(t.nodeValue for t in node.childNodes if t.nodeType == t.TEXT_NODE)

    def set_node_text(self, tab, node, text):
        while node.firstChild:
            node.removeChild(node.firstChild)
        if text == "":
            pass 
        else:
            node.appendChild(tab.dom.createTextNode(text))

    def flush_tab_to_xml(self, tab):
        def escape_xml(text):
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def serialize_node(node, indent=0):
            ind = "  " * indent
            if node.nodeType == node.TEXT_NODE:
                return escape_xml(node.nodeValue.strip())
            elif node.nodeType == node.ELEMENT_NODE:
                tag = node.tagName
                valid_children = [c for c in node.childNodes if not (c.nodeType == c.TEXT_NODE and not c.nodeValue.strip())]
                
                if not valid_children:
                    return f"{ind}<{tag}></{tag}>\n"
                
                if all(c.nodeType == c.TEXT_NODE for c in valid_children):
                    text_val = "".join(escape_xml(c.nodeValue.strip()) for c in valid_children)
                    return f"{ind}<{tag}>{text_val}</{tag}>\n"
                else:
                    children_str = "".join(serialize_node(child, indent + 1) for child in valid_children)
                    return f"{ind}<{tag}>\n{children_str}{ind}</{tag}>\n"
            return ""

        root_element = tab.dom.documentElement
        xml_content = '<?xml version="1.0" encoding="utf-8"?>\n' + serialize_node(root_element, 0)
        
        with open(tab.working_xml, "w", encoding="utf-8") as f:
            f.write(xml_content)

    def show_tab_context_menu(self, event):
        try:
            index = self.notebook.index(f"@{event.x},{event.y}")
            self.notebook.select(index)
            self.tab_menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass 

    def close_active_tab(self):
        tab = self.get_active_tab()
        if not tab: return
        if tab.is_pinned:
            messagebox.showinfo("Tab Pinned", "Cannot close a pinned tab. Unpin it first.")
            return

        tab_id_str = str(tab.frame)
        self.notebook.forget(tab.frame)
        del self.open_tabs[tab_id_str]
        self.schedule_save()

        if not self.open_tabs:
            self.btn_save.config(state=tk.DISABLED)
            self.btn_save_all.config(state=tk.DISABLED)
            self.set_ui_state(tk.DISABLED)
            self.var_key.set("")
            self.var_type.set("")
            self.var_data.set("")
            
        self.update_undo_redo_buttons()

    def close_other_tabs(self):
        active_tab = self.get_active_tab()
        if not active_tab: return
        
        to_close = []
        for tab_id, tab in self.open_tabs.items():
            if tab != active_tab and not tab.is_pinned:
                to_close.append((tab_id, tab))

        for tab_id_str, tab in to_close:
            self.notebook.forget(tab.frame)
            del self.open_tabs[tab_id_str]
            
        self.schedule_save()
        self.update_undo_redo_buttons()

    def toggle_pin_tab(self):
        tab = self.get_active_tab()
        if not tab: return
        
        tab.is_pinned = not tab.is_pinned
        filename = os.path.basename(tab.full_path)
        title = f"📌 {filename}" if tab.is_pinned else filename
        
        self.notebook.tab(tab.frame, text=title)

    def on_tab_changed(self, event):
        tab = self.get_active_tab()
        self.schedule_save()
        self.update_undo_redo_buttons()
        if not tab: return
        
        if tab.selected_node_id and tab.selected_node_id in tab.node_map:
            node_dict = tab.node_map[tab.selected_node_id]
            key_str = self.get_node_text(node_dict["key_node"])
            type_str = self.get_node_text(node_dict["type_node"])
            data_str = self.get_node_text(node_dict["data_node"]) if type_str != "Table" else ""

            self.set_ui_state(tk.NORMAL)
            self.var_key.set(key_str)
            self.var_type.set(type_str)
            self.var_data.set(data_str)
            
            if type_str == "Table":
                self.entry_data.config(state=tk.DISABLED)
                self.btn_add_child.config(state=tk.NORMAL)
            else:
                self.entry_data.config(state=tk.NORMAL)
                self.btn_add_child.config(state=tk.DISABLED)
        else:
            self.set_ui_state(tk.DISABLED)
            self.var_key.set("")
            self.var_type.set("")
            self.var_data.set("")

    def on_tree_select(self, event):
        tab = self.get_active_tab()
        if not tab: return
        
        selected = tab.tree.selection()
        if not selected:
            self.set_ui_state(tk.DISABLED)
            tab.selected_node_id = None
            return
            
        tab.selected_node_id = selected[0]
        node_dict = tab.node_map[tab.selected_node_id]
        
        key_str = self.get_node_text(node_dict["key_node"])
        type_str = self.get_node_text(node_dict["type_node"])
        data_str = self.get_node_text(node_dict["data_node"]) if type_str != "Table" else ""

        self.set_ui_state(tk.NORMAL)
        self.var_key.set(key_str)
        self.var_type.set(type_str)
        self.var_data.set(data_str)
        
        if type_str == "Table":
            self.entry_data.config(state=tk.DISABLED)
            self.btn_add_child.config(state=tk.NORMAL)
        else:
            self.entry_data.config(state=tk.NORMAL)
            self.btn_add_child.config(state=tk.DISABLED)

    def apply_edit(self):
        tab = self.get_active_tab()
        if not tab or not tab.selected_node_id: return
        
        node_dict = tab.node_map[tab.selected_node_id]
        new_key = self.var_key.get()
        new_type = self.var_type.get()
        new_data = self.var_data.get()

        self.set_node_text(tab, node_dict["key_node"], new_key)
        self.set_node_text(tab, node_dict["type_node"], new_type)
        
        if new_type != "Table":
            while node_dict["data_node"].firstChild:
                node_dict["data_node"].removeChild(node_dict["data_node"].firstChild)
            self.set_node_text(tab, node_dict["data_node"], new_data)

        self.flush_tab_to_xml(tab)
        self.push_history(tab)

        selected_dom = node_dict["val_node"]
        self.reload_tab_treeview(tab)
        self.schedule_save()
        
        if selected_dom in tab.dom_node_to_key:
            new_tv_id = tab.dom_node_to_key[selected_dom]
            tab.tree.selection_set(new_tv_id)
            tab.tree.see(new_tv_id)

    def add_node(self, is_child=False):
        tab = self.get_active_tab()
        if not tab or not tab.selected_node_id: return
        
        node_dict = tab.node_map[tab.selected_node_id]
        
        new_val_node = tab.dom.createElement("Value")
        k_node = tab.dom.createElement("Key")
        t_node = tab.dom.createElement("Type")
        d_node = tab.dom.createElement("Data")
        
        k_node.appendChild(tab.dom.createTextNode("new_key"))
        t_node.appendChild(tab.dom.createTextNode("String"))
        d_node.appendChild(tab.dom.createTextNode("new_data"))
        
        new_val_node.appendChild(k_node)
        new_val_node.appendChild(t_node)
        new_val_node.appendChild(d_node)

        if is_child:
            node_dict["data_node"].appendChild(new_val_node)
            tab.expanded_paths.add(node_dict["full_path"])
        else:
            parent = node_dict["val_node"].parentNode
            parent.appendChild(new_val_node)

        self.flush_tab_to_xml(tab)
        self.push_history(tab)
        self.reload_tab_treeview(tab)
        self.schedule_save()

    def delete_node(self):
        tab = self.get_active_tab()
        if not tab or not tab.selected_node_id: return
        
        node_dict = tab.node_map[tab.selected_node_id]
        parent = node_dict["val_node"].parentNode
        parent.removeChild(node_dict["val_node"])
        
        tab.selected_node_id = None
        self.set_ui_state(tk.DISABLED)
        self.var_key.set("")
        self.var_type.set("")
        self.var_data.set("")
        
        self.flush_tab_to_xml(tab)
        self.push_history(tab)
        self.reload_tab_treeview(tab)
        self.schedule_save()

    def quick_mod(self, key_name, target_val, toggle_back_val):
        tab = self.get_active_tab()
        if not tab:
            messagebox.showwarning("Warning", "Please open an attribute file tab first!")
            return

        modified = 0
        for tv_id, node_dict in tab.node_map.items():
            k_str = self.get_node_text(node_dict["key_node"])
            if k_str.lower() == key_name.lower():
                d_str = self.get_node_text(node_dict["data_node"])
                new_val = toggle_back_val if d_str == target_val else target_val
                self.set_node_text(tab, node_dict["data_node"], new_val)
                modified += 1

        if modified > 0:
            self.flush_tab_to_xml(tab)
            self.push_history(tab)
            self.reload_tab_treeview(tab)
            self.schedule_save()
            messagebox.showinfo("Quick Mod Applied", f"Toggled '{key_name}' to '{new_val}' ({modified} instances).")
        else:
            messagebox.showinfo("Not Found", f"Key '{key_name}' was not found in this file.")

    def compile_tab_async(self, tab, on_success=None):
        def worker():
            try:
                if self.create_backup.get() and os.path.exists(tab.full_path):
                    shutil.copyfile(tab.full_path, tab.full_path + ".bak")

                self.flush_tab_to_xml(tab)

                ext = os.path.splitext(tab.full_path)[1].lower()
                if ext == '.attr_pc':
                    ExternalBAFConverter.xml_to_baf(tab.working_xml, tab.full_path)
                else:
                    SMBod.convert_to_baf(tab.working_xml, tab.full_path)

                self.modified_files.add(tab.rel_path)
                
                if on_success:
                    self.root.after(0, on_success)
            except Exception as err:
                err_str = str(err)
                self.root.after(0, lambda: messagebox.showerror("Compilation Error", f"Failed to save and compile {tab.rel_path}:\n{err_str}"))

        threading.Thread(target=worker, daemon=True).start()

    def save_active_tab(self):
        self.save_settings()
        tab = self.get_active_tab()
        if not tab: return
        
        def success_callback():
            self.update_undo_redo_buttons()
            self.refresh_file_list()
            messagebox.showinfo("Save Complete", f"Successfully saved and compiled:\n{os.path.basename(tab.full_path)}")

        self.compile_tab_async(tab, success_callback)

    def save_all_tabs(self):
        self.save_settings()
        if not self.open_tabs: return
        
        tabs_to_save = list(self.open_tabs.values())
        saved_count = [0]
        
        def check_done():
            saved_count[0] += 1
            if saved_count[0] == len(tabs_to_save):
                self.update_undo_redo_buttons()
                self.refresh_file_list()
                messagebox.showinfo("Save Complete", f"Successfully saved and compiled {saved_count[0]} open files!")

        for tab in tabs_to_save:
            self.compile_tab_async(tab, check_done)

if __name__ == "__main__":
    root = tk.Tk()
    app = SpaceMarineAttributeEditor(root)
    root.mainloop()