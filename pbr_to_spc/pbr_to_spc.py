import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
from PIL import Image
import os
import subprocess
import sys

# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_script_dir():
    """Gets the directory where the python script/exe is located."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def check_alpha(image_path):
    """Checks if an image has a non-white alpha channel."""
    try:
        img = Image.open(image_path)
        if img.mode in ('RGBA', 'LA') or 'transparency' in img.info:
            img = img.convert('RGBA')
            alpha = np.array(img.split()[-1])
            if np.min(alpha) < 255:
                return True, alpha
    except Exception:
        pass
    return False, None

def convert_to_dds(png_path, has_alpha):
    """Uses texconv.exe to convert a PNG to DDS with DXT1 or DXT5."""
    texconv_path = os.path.join(get_script_dir(), "texconv.exe")
    format_str = "BC3_UNORM" if has_alpha else "BC1_UNORM"
    save_dir = os.path.dirname(png_path)
    cmd = [texconv_path, "-f", format_str, "-y", "-o", save_dir, png_path]
    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    if os.path.exists(png_path):
        os.remove(png_path)

def convert_dds_to_png(image_path):
    """Decompresses a DDS file into a temporary PNG for processing."""
    if not image_path.lower().endswith('.dds'):
        return image_path, False
        
    texconv_path = os.path.join(get_script_dir(), "texconv.exe")
    save_dir = os.path.dirname(image_path)
    cmd = [texconv_path, "-ft", "png", "-y", "-o", save_dir, image_path]
    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    
    png_path = os.path.splitext(image_path)[0] + ".png"
    return png_path, True

def browse_file(string_var, title):
    filepath = filedialog.askopenfilename(title=title, filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.dds"), ("All Files", "*.*")])
    if filepath:
        string_var.set(filepath)

def browse_directory(string_var, title):
    dirpath = filedialog.askdirectory(title=title)
    if dirpath:
        string_var.set(dirpath)

# ==========================================
# FORWARD CONVERSION (PBR -> LEGACY)
# ==========================================

def core_convert(base_path, met_path, rough_path, ao_path, use_packed, packed_path, emissive_path, nrm_path, invert_green, invert_blue):
    texconv_path = os.path.join(get_script_dir(), "texconv.exe")
    if not os.path.exists(texconv_path):
        raise FileNotFoundError("Please download 'texconv.exe' (Microsoft DirectXTex) and place it in the same folder as this tool.")

    if not base_path:
        raise ValueError("Missing Base Color texture.")

    save_dir = os.path.dirname(base_path)
    base_filename = os.path.splitext(os.path.basename(base_path))[0]
    
    diffuse_png = os.path.join(save_dir, f"{base_filename}_dif.png")
    specular_png = os.path.join(save_dir, f"{base_filename}_spc.png")
    lp_png = os.path.join(save_dir, f"{base_filename}_lp.png")

    has_transparency, alpha_array = check_alpha(base_path)

    img_base = Image.open(base_path).convert('RGB')
    target_size = img_base.size
    base_color = np.array(img_base).astype(np.float32) / 255.0

    if use_packed:
        img_packed = Image.open(packed_path).convert('RGB')
        if img_packed.size != target_size: img_packed = img_packed.resize(target_size)
        packed_data = np.array(img_packed)
        metallic = packed_data[:, :, 0].astype(np.float32) / 255.0
        roughness = packed_data[:, :, 1]  
        ao = packed_data[:, :, 2].astype(np.float32) / 255.0
    else:
        img_met = Image.open(met_path).convert('L')
        img_rough = Image.open(rough_path).convert('L')
        if img_met.size != target_size: img_met = img_met.resize(target_size)
        if img_rough.size != target_size: img_rough = img_rough.resize(target_size)
        metallic = np.array(img_met).astype(np.float32) / 255.0
        roughness = np.array(img_rough)
        
        if ao_path and os.path.exists(ao_path):
            img_ao = Image.open(ao_path).convert('L')
            if img_ao.size != target_size: img_ao = img_ao.resize(target_size)
        else:
            img_ao = Image.new('L', target_size, 255) 
        ao = np.array(img_ao).astype(np.float32) / 255.0

    metallic_3c = np.stack((metallic,)*3, axis=-1)
    ao_3c = np.stack((ao,)*3, axis=-1)

    # Legacy Diffuse
    diffuse = base_color * (1.0 - metallic_3c) * ao_3c
    diffuse_rgb = np.clip(diffuse * 255.0, 0, 255).astype(np.uint8)
    if has_transparency:
        diffuse_img = Image.fromarray(np.dstack((diffuse_rgb, alpha_array)), mode='RGBA')
    else:
        diffuse_img = Image.fromarray(diffuse_rgb, mode='RGB')
    diffuse_img.save(diffuse_png)

    # Specular
    dielectric_base = np.full_like(base_color, 0.22)
    specular = (base_color * metallic_3c) + (dielectric_base * (1.0 - metallic_3c))
    specular_img = Image.fromarray(np.clip(specular * ao_3c * 255.0, 0, 255).astype(np.uint8))
    specular_img.save(specular_png)

    # LP (R=Glossiness, G=Emissive, B=Metallic)
    gloss_val = np.clip(255 - roughness, 0, 255).astype(np.uint8)
    if emissive_path and os.path.exists(emissive_path):
        img_emissive = Image.open(emissive_path).convert('L')
        if img_emissive.size != target_size: img_emissive = img_emissive.resize(target_size)
        emissive_val = np.array(img_emissive)
    else:
        emissive_val = np.zeros_like(gloss_val)
        
    metallic_val = np.clip(metallic * 255.0, 0, 255).astype(np.uint8)

    lp_img = Image.fromarray(np.stack((gloss_val, emissive_val, metallic_val), axis=-1), mode='RGB')
    lp_img.save(lp_png)

    convert_to_dds(diffuse_png, has_transparency)  
    convert_to_dds(specular_png, False)            
    convert_to_dds(lp_png, False)                  
    created_files = [f"{base_filename}_dif.dds", f"{base_filename}_spc.dds", f"{base_filename}_lp.dds"]

    # Normal Map
    if nrm_path and os.path.exists(nrm_path):
        nrm_png = os.path.join(save_dir, f"{base_filename}_nrm.png")
        img_nrm = Image.open(nrm_path).convert('RGB')
        if img_nrm.size != target_size: img_nrm = img_nrm.resize(target_size)
        nrm_array = np.array(img_nrm)
        if invert_green: nrm_array[:, :, 1] = 255 - nrm_array[:, :, 1]
        if invert_blue: nrm_array[:, :, 2] = 255 - nrm_array[:, :, 2]
        Image.fromarray(nrm_array).save(nrm_png)
        convert_to_dds(nrm_png, False)
        created_files.append(f"{base_filename}_nrm.dds")

    return created

# ==========================================
# REVERSE CONVERSION (LEGACY -> PBR)
# ==========================================

def core_reverse(dif_path, spc_path, lp_path, nrm_path, invert_green, invert_blue, pack_output=False):
    if not dif_path or not os.path.exists(dif_path): raise ValueError("Missing Diffuse texture.")
    if not spc_path or not os.path.exists(spc_path): raise ValueError("Missing Specular texture.")

    save_dir = os.path.dirname(dif_path)
    
    # Strip suffixes to get root name
    base_filename = os.path.basename(dif_path)
    for sfx in ['_dif.png', '_dif.dds', '_dif.tga']:
        if base_filename.lower().endswith(sfx):
            base_filename = base_filename[: -len(sfx)]
            break

    # Decompress DDS to PNG if necessary
    d_path, d_del = convert_dds_to_png(dif_path)
    s_path, s_del = convert_dds_to_png(spc_path)
    
    # Handle optional LP texture
    has_lp = bool(lp_path and os.path.exists(lp_path))
    if has_lp:
        l_path, l_del = convert_dds_to_png(lp_path)
    else:
        l_path, l_del = None, False

    # Load images
    img_dif = Image.open(d_path).convert('RGBA')
    target_size = img_dif.size 

    img_spc = Image.open(s_path).convert('RGB')
    if img_spc.size != target_size:
        img_spc = img_spc.resize(target_size, Image.Resampling.BICUBIC)

    if has_lp:
        img_lp = Image.open(l_path).convert('RGB')
        if img_lp.size != target_size:
            img_lp = img_lp.resize(target_size, Image.Resampling.BICUBIC)
        lp_arr = np.array(img_lp).astype(np.float32) / 255.0
    else:
        # Fallback to Blank Red Texture if LP map is missing
        lp_arr = np.zeros((target_size[1], target_size[0], 3), dtype=np.float32)
        lp_arr[:, :, 0] = 1.0 # Pure Red, G=0, B=0

    # Convert to 0.0 - 1.0 arrays
    dif_arr = np.array(img_dif).astype(np.float32) / 255.0
    spc_arr = np.array(img_spc).astype(np.float32) / 255.0

    # Extract Node Graph Inputs
    lp_red = lp_arr[:, :, 0] 
    lp_blue = lp_arr[:, :, 2] 
    spc_lum = np.dot(spc_arr[...,:3], [0.2126, 0.7152, 0.0722]) # Specular used as Factor

    # --- 1. BASE COLOR (Global HSV Value = 2) ---
    # Multiply the entire diffuse RGB by 2 globally, as requested
    base_color_rgb = dif_arr[...,:3] * 2.0
    
    base_color_img = Image.fromarray(np.clip(base_color_rgb * 255.0, 0, 255).astype(np.uint8))
    if np.min(dif_arr[...,3]) < 1.0:
        alpha_img = Image.fromarray(np.clip(dif_arr[...,3] * 255, 0, 255).astype(np.uint8))
        base_color_img = Image.merge("RGBA", (*base_color_img.split(), alpha_img))
    
    base_color_img.save(os.path.join(save_dir, f"{base_filename}_BaseColor.png"))
    created = [f"{base_filename}_BaseColor.png"]

    # --- 2. EXACT METALLIC NODE GRAPH ---
    metallic = (lp_blue * (1.0 - spc_lum)) + (1.0 * spc_lum)

    # --- 3. EXACT ROUGHNESS NODE GRAPH ---
    m_curve = np.where(lp_blue < 0.050, 
                       lp_blue * (0.9250 / 0.050), 
                       0.9250 + (lp_blue - 0.050) * ((1.0 - 0.9250) / (1.0 - 0.050)))
    m_curve = np.clip(m_curve, 0.0, 1.0)

    inv_r = (lp_red * (1.0 - 0.700)) + ((1.0 - lp_red) * 0.700)
    inv_m = (m_curve * (1.0 - 0.550)) + ((1.0 - m_curve) * 0.550)

    roughness = (inv_r * (1.0 - m_curve)) + (inv_m * m_curve)
    
    # --- 4. HSV VALUE MASKING (LP Blue Channel as Factor) ---
    roughness = (roughness * (1.0 - lp_blue)) + ((roughness * 0.0) * lp_blue)
    roughness = np.clip(roughness, 0.0, 1.0)

    metallic = (metallic * (1.0 - lp_blue)) + ((metallic * 2.0) * lp_blue)
    metallic = np.clip(metallic, 0.0, 1.0)

    # --- 5. IMAGE EXPORT (PACKED OR INDIVIDUAL) ---
    if pack_output:
        packed_r = np.clip(metallic * 255.0, 0, 255).astype(np.uint8)
        packed_g = np.clip(roughness * 255.0, 0, 255).astype(np.uint8)
        packed_b = np.full_like(packed_r, 255) # Pure White
        
        packed_rgb = np.stack((packed_r, packed_g, packed_b), axis=-1)
        Image.fromarray(packed_rgb, mode='RGB').save(os.path.join(save_dir, f"{base_filename}_Packed.png"))
        created.append(f"{base_filename}_Packed.png")
    else:
        Image.fromarray(np.clip(metallic * 255.0, 0, 255).astype(np.uint8)).save(os.path.join(save_dir, f"{base_filename}_Metallic.png"))
        Image.fromarray(np.clip(roughness * 255.0, 0, 255).astype(np.uint8)).save(os.path.join(save_dir, f"{base_filename}_Roughness.png"))
        created.extend([f"{base_filename}_Metallic.png", f"{base_filename}_Roughness.png"])

    # --- FINAL CLEANUP ---
    if np.max(lp_arr[:, :, 1]) > 0:
        Image.fromarray(np.clip(lp_arr[:, :, 1] * 255.0, 0, 255).astype(np.uint8)).save(os.path.join(save_dir, f"{base_filename}_Emissive.png"))
    
    if d_del: os.remove(d_path)
    if s_del: os.remove(s_path)
    if l_del: os.remove(l_path)

    # Normal Maps
    if nrm_path and os.path.exists(nrm_path):
        n_path, n_del = convert_dds_to_png(nrm_path)
        img_nrm = Image.open(n_path).convert('RGB')
        
        if img_nrm.size != target_size:
            img_nrm = img_nrm.resize(target_size, Image.Resampling.BICUBIC)
            
        nrm_arr = np.array(img_nrm)
        if invert_green: nrm_arr[:, :, 1] = 255 - nrm_arr[:, :, 1]
        if invert_blue: nrm_arr[:, :, 2] = 255 - nrm_arr[:, :, 2]
        
        Image.fromarray(nrm_arr).save(os.path.join(save_dir, f"{base_filename}_Normal.png"))
        if n_del: os.remove(n_path)
        created.append(f"{base_filename}_Normal.png")

    return created

# ==========================================
# GUI AND MAIN LOGIC
# ==========================================

def run_single_conversion(vars_dict):
    try:
        created = core_convert(
            vars_dict['base'].get(), vars_dict['met'].get(), vars_dict['rough'].get(), vars_dict['ao'].get(),
            vars_dict['use_packed'].get(), vars_dict['packed'].get(), vars_dict['emissive'].get(),
            vars_dict['nrm'].get(), vars_dict['inv_g'].get(), vars_dict['inv_b'].get()
        )
        messagebox.showinfo("Success", "Textures converted successfully!\n\nCreated:\n" + "\n".join(created))
    except Exception as e:
        messagebox.showerror("Conversion Error", str(e))

def run_single_reverse(vars_dict):
    try:
        created = core_reverse(
            vars_dict['dif'].get(), vars_dict['spc'].get(), vars_dict['lp'].get(), 
            vars_dict['nrm'].get(), vars_dict['inv_g'].get(), vars_dict['inv_b'].get(),
            vars_dict['pack'].get()
        )
        messagebox.showinfo("Success", "Legacy textures unpacked to PBR successfully!\n\nCreated:\n" + "\n".join(created))
    except Exception as e:
        messagebox.showerror("Reverse Conversion Error", str(e))

def run_batch_conversion(vars_dict, mode="forward"):
    directory = vars_dict['dir'].get()
    if not directory or not os.path.exists(directory):
        messagebox.showwarning("Error", "Please select a valid directory.")
        return

    valid_exts = ['.png', '.jpg', '.jpeg', '.tga', '.dds']
    success_count, errors = 0, []

    def find_map(base_name, suffix):
        if not suffix: return ""
        for ext in valid_exts:
            p = os.path.join(directory, base_name + suffix + ext)
            if os.path.exists(p): return p
        return ""

    for file in os.listdir(directory):
        name, ext = os.path.splitext(file)
        if ext.lower() in valid_exts:
            if mode == "forward" and name.endswith(vars_dict['base_sfx'].get()):
                base_sfx = vars_dict['base_sfx'].get()
                base_name = name[:-len(base_sfx)] 
                
                try:
                    core_convert(
                        os.path.join(directory, file), find_map(base_name, vars_dict['met_sfx'].get()), 
                        find_map(base_name, vars_dict['rough_sfx'].get()), find_map(base_name, vars_dict['ao_sfx'].get()), 
                        False, "", find_map(base_name, vars_dict['emissive_sfx'].get()), 
                        find_map(base_name, vars_dict['nrm_sfx'].get()), 
                        vars_dict['inv_g'].get(), vars_dict['inv_b'].get()
                    )
                    success_count += 1
                except Exception as e:
                    errors.append(f"{base_name}: {str(e)}")

            elif mode == "reverse" and name.endswith(vars_dict['dif_sfx'].get()):
                dif_sfx = vars_dict['dif_sfx'].get()
                base_name = name[:-len(dif_sfx)] 
                
                try:
                    core_reverse(
                        os.path.join(directory, file), find_map(base_name, vars_dict['spc_sfx'].get()),
                        find_map(base_name, vars_dict['lp_sfx'].get()), find_map(base_name, vars_dict['nrm_sfx'].get()),
                        vars_dict['inv_g'].get(), vars_dict['inv_b'].get(), vars_dict['pack'].get()
                    )
                    success_count += 1
                except Exception as e:
                    errors.append(f"{base_name}: {str(e)}")

    if success_count > 0 and not errors:
        messagebox.showinfo("Batch Complete", f"Successfully processed {success_count} material(s).")
    elif errors:
        err_msg = "\n".join(errors[:5])
        messagebox.showerror("Batch Results", f"Processed {success_count} material(s).\nErrors encountered:\n{err_msg}")
    else:
        messagebox.showinfo("Batch Complete", "No matching files found in the directory.")


def main():
    root = tk.Tk()
    root.title("PBR <-> Legacy Texture Converter")
    root.geometry("640x520") 
    root.resizable(False, False)

    notebook = ttk.Notebook(root)
    notebook.pack(expand=True, fill="both", padx=10, pady=10)

    frame_single_fwd = ttk.Frame(notebook)
    frame_batch_fwd = ttk.Frame(notebook)
    frame_single_rev = ttk.Frame(notebook)
    frame_batch_rev = ttk.Frame(notebook)
    
    notebook.add(frame_single_fwd, text="Single PBR->Legacy")
    notebook.add(frame_batch_fwd, text="Batch PBR->Legacy")
    notebook.add(frame_single_rev, text="Single Legacy->PBR")
    notebook.add(frame_batch_rev, text="Batch Legacy->PBR")

    pad, bw = {'padx': 10, 'pady': 5}, 18

    # --- TAB 1: SINGLE PBR TO LEGACY ---
    s_vars = {'base': tk.StringVar(), 'packed': tk.StringVar(), 'met': tk.StringVar(), 'rough': tk.StringVar(), 'ao': tk.StringVar(), 'emissive': tk.StringVar(), 'nrm': tk.StringVar(), 'use_packed': tk.BooleanVar(value=False), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}

    tk.Button(frame_single_fwd, text="Base Color", width=bw, command=lambda: browse_file(s_vars['base'], "Select Base Color")).grid(row=0, column=0, **pad)
    tk.Entry(frame_single_fwd, textvariable=s_vars['base'], width=50, state='readonly').grid(row=0, column=1, **pad)
    
    tk.Checkbutton(frame_single_fwd, text="Use Packed Texture (R=Met, G=Rough, B=AO)", variable=s_vars['use_packed'], font=("Arial", 9, "bold")).grid(row=1, column=0, columnspan=2, pady=(5, 0), sticky="w", padx=10)
    
    btn_packed = tk.Button(frame_single_fwd, text="Packed (R,G,B)", width=bw, command=lambda: browse_file(s_vars['packed'], "Select Packed Texture"))
    btn_packed.grid(row=2, column=0, **pad)
    ent_packed = tk.Entry(frame_single_fwd, textvariable=s_vars['packed'], width=50)
    ent_packed.grid(row=2, column=1, **pad)
    
    btn_met = tk.Button(frame_single_fwd, text="Metallic", width=bw, command=lambda: browse_file(s_vars['met'], "Select Metallic"))
    btn_met.grid(row=3, column=0, **pad)
    ent_met = tk.Entry(frame_single_fwd, textvariable=s_vars['met'], width=50)
    ent_met.grid(row=3, column=1, **pad)
    
    btn_rough = tk.Button(frame_single_fwd, text="Roughness", width=bw, command=lambda: browse_file(s_vars['rough'], "Select Roughness"))
    btn_rough.grid(row=4, column=0, **pad)
    ent_rough = tk.Entry(frame_single_fwd, textvariable=s_vars['rough'], width=50)
    ent_rough.grid(row=4, column=1, **pad)
    
    tk.Button(frame_single_fwd, text="AO (Optional)", width=bw, command=lambda: browse_file(s_vars['ao'], "Select AO")).grid(row=5, column=0, **pad)
    tk.Entry(frame_single_fwd, textvariable=s_vars['ao'], width=50, state='readonly').grid(row=5, column=1, **pad)
    tk.Button(frame_single_fwd, text="Emissive (Optional)", width=bw, command=lambda: browse_file(s_vars['emissive'], "Select Emissive")).grid(row=6, column=0, **pad)
    tk.Entry(frame_single_fwd, textvariable=s_vars['emissive'], width=50, state='readonly').grid(row=6, column=1, **pad)
    tk.Button(frame_single_fwd, text="Normal Map (Opt)", width=bw, command=lambda: browse_file(s_vars['nrm'], "Select Normal Map")).grid(row=7, column=0, **pad)
    tk.Entry(frame_single_fwd, textvariable=s_vars['nrm'], width=50, state='readonly').grid(row=7, column=1, **pad)
    
    opts = tk.Frame(frame_single_fwd)
    opts.grid(row=8, column=1, sticky="w", padx=5)
    tk.Checkbutton(opts, text="Invert Green (Y)", variable=s_vars['inv_g']).pack(side="left")
    tk.Checkbutton(opts, text="Invert Blue (Z)", variable=s_vars['inv_b']).pack(side="left", padx=10)
    
    def toggle_single(*args):
        sp = 'normal' if s_vars['use_packed'].get() else 'disabled'
        si = 'disabled' if s_vars['use_packed'].get() else 'normal'
        btn_packed.config(state=sp); ent_packed.config(state='readonly' if sp=='normal' else 'disabled')
        btn_met.config(state=si); ent_met.config(state='readonly' if si=='normal' else 'disabled')
        btn_rough.config(state=si); ent_rough.config(state='readonly' if si=='normal' else 'disabled')
    s_vars['use_packed'].trace_add("write", toggle_single); toggle_single()
    
    tk.Button(frame_single_fwd, text="CONVERT TO DDS", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=lambda: run_single_conversion(s_vars)).grid(row=9, column=0, columnspan=2, pady=10, ipadx=10, ipady=5)

    # --- TAB 2: BATCH PBR TO LEGACY ---
    bf_vars = {'dir': tk.StringVar(), 'base_sfx': tk.StringVar(value="_BaseColor"), 'met_sfx': tk.StringVar(value="_Metallic"), 'rough_sfx': tk.StringVar(value="_Roughness"), 'ao_sfx': tk.StringVar(value="_AO"), 'emissive_sfx': tk.StringVar(value="_Emissive"), 'nrm_sfx': tk.StringVar(value="_Normal"), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}
    tk.Label(frame_batch_fwd, text="Select folder to process all PBR files into Legacy Textures.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(frame_batch_fwd, text="Select Directory", width=bw, command=lambda: browse_directory(bf_vars['dir'], "Select Dir")).grid(row=1, column=0, **pad)
    tk.Entry(frame_batch_fwd, textvariable=bf_vars['dir'], width=50, state='readonly').grid(row=1, column=1, **pad)
    
    labels = ["Base Color Suffix:", "Metallic Suffix:", "Roughness Suffix:", "Normal Suffix:", "AO Suffix (Opt):", "Emissive Suffix (Opt):"]
    vars_list = ['base_sfx', 'met_sfx', 'rough_sfx', 'nrm_sfx', 'ao_sfx', 'emissive_sfx']
    for i, (l, v) in enumerate(zip(labels, vars_list)):
        tk.Label(frame_batch_fwd, text=l).grid(row=2+i, column=0, sticky="e", **pad)
        tk.Entry(frame_batch_fwd, textvariable=bf_vars[v], width=30).grid(row=2+i, column=1, sticky="w", **pad)
        
    bf_opts = tk.Frame(frame_batch_fwd)
    bf_opts.grid(row=8, column=1, sticky="w", padx=5, pady=5)
    tk.Checkbutton(bf_opts, text="Invert Green (Y)", variable=bf_vars['inv_g']).pack(side="left")
    tk.Checkbutton(bf_opts, text="Invert Blue (Z)", variable=bf_vars['inv_b']).pack(side="left", padx=10)
    
    tk.Button(frame_batch_fwd, text="START BATCH CONVERSION", bg="#2196F3", fg="white", font=("Arial", 10, "bold"), command=lambda: run_batch_conversion(bf_vars, "forward")).grid(row=9, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- TAB 3: SINGLE LEGACY TO PBR ---
    sr_vars = {'dif': tk.StringVar(), 'spc': tk.StringVar(), 'lp': tk.StringVar(), 'nrm': tk.StringVar(), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False), 'pack': tk.BooleanVar(value=False)}

    tk.Label(frame_single_rev, text="Unpack individual Legacy DDS/PNG textures back to PBR PNGs.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    
    tk.Button(frame_single_rev, text="Diffuse (_dif)", width=bw, command=lambda: browse_file(sr_vars['dif'], "Select Diffuse")).grid(row=1, column=0, **pad)
    tk.Entry(frame_single_rev, textvariable=sr_vars['dif'], width=50, state='readonly').grid(row=1, column=1, **pad)
    
    tk.Button(frame_single_rev, text="Specular (_spc)", width=bw, command=lambda: browse_file(sr_vars['spc'], "Select Specular")).grid(row=2, column=0, **pad)
    tk.Entry(frame_single_rev, textvariable=sr_vars['spc'], width=50, state='readonly').grid(row=2, column=1, **pad)
    
    tk.Button(frame_single_rev, text="LP / Gloss (_lp)", width=bw, command=lambda: browse_file(sr_vars['lp'], "Select LP Map")).grid(row=3, column=0, **pad)
    tk.Entry(frame_single_rev, textvariable=sr_vars['lp'], width=50, state='readonly').grid(row=3, column=1, **pad)
    
    tk.Button(frame_single_rev, text="Normal Map (Opt)", width=bw, command=lambda: browse_file(sr_vars['nrm'], "Select Normal Map")).grid(row=4, column=0, **pad)
    tk.Entry(frame_single_rev, textvariable=sr_vars['nrm'], width=50, state='readonly').grid(row=4, column=1, **pad)
    
    sr_opts = tk.Frame(frame_single_rev)
    sr_opts.grid(row=5, column=1, sticky="w", padx=5, pady=(10, 0))
    tk.Checkbutton(sr_opts, text="Invert Green (Y)", variable=sr_vars['inv_g']).pack(side="left")
    tk.Checkbutton(sr_opts, text="Invert Blue (Z)", variable=sr_vars['inv_b']).pack(side="left", padx=10)
    
    sr_pack_opts = tk.Frame(frame_single_rev)
    sr_pack_opts.grid(row=6, column=1, sticky="w", padx=5, pady=(5, 10))
    tk.Checkbutton(sr_pack_opts, text="Export Packed Texture (R=Met, G=Rough, B=White)", variable=sr_vars['pack'], font=("Arial", 9, "bold")).pack(side="left")
    
    tk.Button(frame_single_rev, text="REVERSE TO PBR", bg="#E91E63", fg="white", font=("Arial", 10, "bold"), command=lambda: run_single_reverse(sr_vars)).grid(row=7, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- TAB 4: BATCH LEGACY TO PBR ---
    br_vars = {'dir': tk.StringVar(), 'dif_sfx': tk.StringVar(value="_dif"), 'spc_sfx': tk.StringVar(value="_spc"), 'lp_sfx': tk.StringVar(value="_lp"), 'nrm_sfx': tk.StringVar(value="_nrm"), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False), 'pack': tk.BooleanVar(value=False)}
    tk.Label(frame_batch_rev, text="Select folder to unpack Legacy Textures back into PBR PNGs.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(frame_batch_rev, text="Select Directory", width=bw, command=lambda: browse_directory(br_vars['dir'], "Select Dir")).grid(row=1, column=0, **pad)
    tk.Entry(frame_batch_rev, textvariable=br_vars['dir'], width=50, state='readonly').grid(row=1, column=1, **pad)
    
    r_labels = ["Diffuse Suffix:", "Specular Suffix:", "LP / Gloss Suffix:", "Normal Suffix:"]
    r_vars_list = ['dif_sfx', 'spc_sfx', 'lp_sfx', 'nrm_sfx']
    for i, (l, v) in enumerate(zip(r_labels, r_vars_list)):
        tk.Label(frame_batch_rev, text=l).grid(row=2+i, column=0, sticky="e", **pad)
        tk.Entry(frame_batch_rev, textvariable=br_vars[v], width=30).grid(row=2+i, column=1, sticky="w", **pad)
        
    br_opts = tk.Frame(frame_batch_rev)
    br_opts.grid(row=6, column=1, sticky="w", padx=5, pady=(20, 0))
    tk.Checkbutton(br_opts, text="Invert Green (Y)", variable=br_vars['inv_g']).pack(side="left")
    tk.Checkbutton(br_opts, text="Invert Blue (Z)", variable=br_vars['inv_b']).pack(side="left", padx=10)
    
    br_pack_opts = tk.Frame(frame_batch_rev)
    br_pack_opts.grid(row=7, column=1, sticky="w", padx=5, pady=(5, 15))
    tk.Checkbutton(br_pack_opts, text="Export Packed Textures (R=Met, G=Rough, B=White)", variable=br_vars['pack'], font=("Arial", 9, "bold")).pack(side="left")
    
    tk.Button(frame_batch_rev, text="REVERSE TO PBR", bg="#E91E63", fg="white", font=("Arial", 10, "bold"), command=lambda: run_batch_conversion(br_vars, "reverse")).grid(row=8, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    root.mainloop()

if __name__ == "__main__":
    main()