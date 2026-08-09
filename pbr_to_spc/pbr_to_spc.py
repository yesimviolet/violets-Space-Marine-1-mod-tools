import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
from PIL import Image
import os
import subprocess
import sys
import re

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

def browse_file(string_var, title, is_vmt=False):
    file_types = [("VMT Files", "*.vmt"), ("All Files", "*.*")] if is_vmt else [("Image Files", "*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.dds"), ("All Files", "*.*")]
    filepath = filedialog.askopenfilename(title=title, filetypes=file_types)
    if filepath:
        string_var.set(filepath)

def browse_directory(string_var, title):
    dirpath = filedialog.askdirectory(title=title)
    if dirpath:
        string_var.set(dirpath)

def get_known_suffixes(vars_dict, exclude_key):
    """Collects all defined suffixes to avoid grabbing secondary maps as base textures."""
    suffixes = []
    for k, v_var in vars_dict.items():
        if k.endswith('_sfx') and k != exclude_key:
            val = v_var.get().strip()
            if val and val.lower() != '/na/':
                suffixes.append(val)
    return suffixes

# ==========================================
# FORWARD CONVERSION (PBR -> SM1)
# ==========================================

def core_convert(base_path, met_path, rough_path, ao_path, use_packed, packed_path, emissive_path, nrm_path, cc_path, invert_green, invert_blue, out_dir):
    texconv_path = os.path.join(get_script_dir(), "texconv.exe")
    if not os.path.exists(texconv_path):
        raise FileNotFoundError("Please download 'texconv.exe' (Microsoft DirectXTex) and place it in the same folder as this tool.")

    if not base_path:
        raise ValueError("Missing Base Color texture.")

    save_dir = out_dir if out_dir else os.path.dirname(base_path)
    if not os.path.exists(save_dir): os.makedirs(save_dir)

    base_filename = os.path.splitext(os.path.basename(base_path))[0]
    
    diffuse_png = os.path.join(save_dir, f"{base_filename}_dif.png")
    specular_png = os.path.join(save_dir, f"{base_filename}_spc.png")
    lp_png = os.path.join(save_dir, f"{base_filename}_lp.png")

    has_transparency, alpha_array = check_alpha(base_path)

    img_base = Image.open(base_path).convert('RGB')
    target_size = img_base.size
    base_color = np.array(img_base).astype(np.float32) / 255.0

    if use_packed and packed_path and os.path.exists(packed_path):
        img_packed = Image.open(packed_path).convert('RGB')
        if img_packed.size != target_size: img_packed = img_packed.resize(target_size)
        packed_data = np.array(img_packed)
        metallic = packed_data[:, :, 0].astype(np.float32) / 255.0
        roughness = packed_data[:, :, 1]  
        ao = packed_data[:, :, 2].astype(np.float32) / 255.0
    else:
        if met_path and os.path.exists(met_path):
            img_met = Image.open(met_path).convert('L')
            if img_met.size != target_size: img_met = img_met.resize(target_size)
            metallic = np.array(img_met).astype(np.float32) / 255.0
        else:
            metallic = np.zeros((target_size[1], target_size[0]), dtype=np.float32)

        if rough_path and os.path.exists(rough_path):
            img_rough = Image.open(rough_path).convert('L')
            if img_rough.size != target_size: img_rough = img_rough.resize(target_size)
            roughness = np.array(img_rough)
        else:
            roughness = np.full((target_size[1], target_size[0]), 127, dtype=np.uint8)
        
        if ao_path and os.path.exists(ao_path):
            img_ao = Image.open(ao_path).convert('L')
            if img_ao.size != target_size: img_ao = img_ao.resize(target_size)
        else:
            img_ao = Image.new('L', target_size, 255) 
        ao = np.array(img_ao).astype(np.float32) / 255.0

    metallic_3c = np.stack((metallic,)*3, axis=-1)
    ao_3c = np.stack((ao,)*3, axis=-1)

    # SM1 Diffuse
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

    # LP (R=Glossiness, G=Emissive, B=Metallic or CC Blue Channel)
    gloss_val = np.clip(255 - roughness, 0, 255).astype(np.uint8)
    if emissive_path and os.path.exists(emissive_path):
        img_emissive = Image.open(emissive_path).convert('L')
        if img_emissive.size != target_size: img_emissive = img_emissive.resize(target_size)
        emissive_val = np.array(img_emissive)
    else:
        emissive_val = np.zeros_like(gloss_val)
        
    if cc_path and os.path.exists(cc_path):
        c_path, c_del = convert_dds_to_png(cc_path)
        img_cc = Image.open(c_path).convert('RGB')
        if img_cc.size != target_size: img_cc = img_cc.resize(target_size)
        cc_arr = np.array(img_cc)
        metallic_val = cc_arr[:, :, 2] 
        if c_del: os.remove(c_path)
    else:
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

    return created_files

# ==========================================
# REVERSE CONVERSION (SM1 -> PBR)
# ==========================================

def core_reverse(dif_path, spc_path, lp_path, nrm_path, cc_path, invert_green, invert_blue, pack_output, out_dir):
    if not dif_path or not os.path.exists(dif_path): raise ValueError("Missing Diffuse texture.")
    if not spc_path or not os.path.exists(spc_path): raise ValueError("Missing Specular texture.")

    save_dir = out_dir if out_dir else os.path.dirname(dif_path)
    if not os.path.exists(save_dir): os.makedirs(save_dir)

    base_filename = os.path.basename(dif_path)
    for sfx in ['_dif.png', '_dif.dds', '_dif.tga']:
        if base_filename.lower().endswith(sfx):
            base_filename = base_filename[: -len(sfx)]
            break

    d_path, d_del = convert_dds_to_png(dif_path)
    s_path, s_del = convert_dds_to_png(spc_path)
    
    has_lp = bool(lp_path and os.path.exists(lp_path))
    if has_lp:
        l_path, l_del = convert_dds_to_png(lp_path)
    else:
        l_path, l_del = None, False

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
        lp_arr = np.zeros((target_size[1], target_size[0], 3), dtype=np.float32)
        lp_arr[:, :, 0] = 1.0 # Pure Red fallback

    dif_arr = np.array(img_dif).astype(np.float32) / 255.0
    spc_arr = np.array(img_spc).astype(np.float32) / 255.0

    lp_red = lp_arr[:, :, 0] 
    lp_blue = lp_arr[:, :, 2] 
    spc_lum = np.dot(spc_arr[...,:3], [0.2126, 0.7152, 0.0722]) 

    # --- 1. BASE COLOR (Global HSV Value = 2) ---
    base_color_rgb = np.clip(dif_arr[...,:3] * 2.0, 0.0, 1.0)
    base_color_img = Image.fromarray((base_color_rgb * 255.0).astype(np.uint8))
    
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

    # --- 5. IMAGE EXPORT ---
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

    # --- CC MAP ---
    if cc_path and os.path.exists(cc_path):
        c_path, c_del = convert_dds_to_png(cc_path)
        img_cc = Image.open(c_path).convert('RGBA')
        if img_cc.size != target_size: img_cc = img_cc.resize(target_size, Image.Resampling.BICUBIC)
        img_cc.save(os.path.join(save_dir, f"{base_filename}_CC.png"))
        if c_del: os.remove(c_path)
        created.append(f"{base_filename}_CC.png")

    # --- FINAL CLEANUP ---
    if np.max(lp_arr[:, :, 1]) > 0:
        Image.fromarray(np.clip(lp_arr[:, :, 1] * 255.0, 0, 255).astype(np.uint8)).save(os.path.join(save_dir, f"{base_filename}_Emissive.png"))
    
    if d_del: os.remove(d_path)
    if s_del: os.remove(s_path)
    if l_del: os.remove(l_path)

    if nrm_path and os.path.exists(nrm_path):
        n_path, n_del = convert_dds_to_png(nrm_path)
        img_nrm = Image.open(n_path).convert('RGB')
        if img_nrm.size != target_size: img_nrm = img_nrm.resize(target_size, Image.Resampling.BICUBIC)
        nrm_arr = np.array(img_nrm)
        if invert_green: nrm_arr[:, :, 1] = 255 - nrm_arr[:, :, 1]
        if invert_blue: nrm_arr[:, :, 2] = 255 - nrm_arr[:, :, 2]
        Image.fromarray(nrm_arr).save(os.path.join(save_dir, f"{base_filename}_Normal.png"))
        if n_del: os.remove(n_path)
        created.append(f"{base_filename}_Normal.png")

    return created

# ==========================================
# SFM TO SM1 CONVERSION
# ==========================================

def find_local_texture(vmt_dir, match_group):
    if not match_group: return ""
    base_name = os.path.basename(match_group.group(1).replace('\\', '/'))
    if base_name.lower().endswith('.vtf'): base_name = base_name[:-4]
    
    for ext in ['.png', '.tga', '.jpg', '.dds']:
        p = os.path.join(vmt_dir, base_name + ext)
        if os.path.exists(p): return p
    return ""

def core_sfm_to_sm1(dif_path, nrm_path, vmt_path, out_dir, invert_green, invert_blue):
    if vmt_path and os.path.exists(vmt_path):
        vmt_dir = os.path.dirname(vmt_path)
        with open(vmt_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        base_match = re.search(r'\$basetexture\s*"?([^"\s]+)"?', content, re.IGNORECASE)
        bump_match = re.search(r'\$bumpmap\s*"?([^"\s]+)"?', content, re.IGNORECASE)
        
        found_dif = find_local_texture(vmt_dir, base_match)
        found_nrm = find_local_texture(vmt_dir, bump_match)
        if found_dif: dif_path = found_dif
        if found_nrm: nrm_path = found_nrm

    if not dif_path or not os.path.exists(dif_path):
        raise ValueError(f"Diffuse texture not found or not mapped in VMT.")
    if not nrm_path or not os.path.exists(nrm_path):
        raise ValueError(f"Normal map not found or not mapped in VMT. Required for Phong mask.")

    save_dir = out_dir if out_dir else os.path.dirname(dif_path)
    if not os.path.exists(save_dir): os.makedirs(save_dir)
    
    base_filename = os.path.splitext(os.path.basename(dif_path))[0]
    created = []

    # 1. Process Diffuse
    img_dif = Image.open(dif_path).convert('RGBA')
    target_size = img_dif.size
    dif_png = os.path.join(save_dir, f"{base_filename}_dif.png")
    img_dif.save(dif_png)
    
    has_alpha, _ = check_alpha(dif_path)
    convert_to_dds(dif_png, has_alpha)
    created.append(f"{base_filename}_dif.dds")

    # 2. Process Normal & Specular (Phong Mask Colorized via Diffuse)
    img_nrm = Image.open(nrm_path)
    if img_nrm.size != target_size: img_nrm = img_nrm.resize(target_size, Image.Resampling.BICUBIC)
    
    img_nrm_rgba = img_nrm.convert('RGBA')
    nrm_arr = np.array(img_nrm_rgba)

    # Specular Construction
    dif_rgb = np.array(img_dif.convert('RGB')).astype(np.float32) / 255.0
    spc_mask = nrm_arr[:, :, 3].astype(np.float32) / 255.0 # Extract Alpha
    spc_mask_3c = np.stack((spc_mask,)*3, axis=-1)
    
    # Multiply the diffuse color by the alpha mask and boost brightness by 2x.
    spc_rgb = np.clip(dif_rgb * spc_mask_3c * 2.0, 0.0, 1.0)
    
    spc_png = os.path.join(save_dir, f"{base_filename}_spc.png")
    Image.fromarray(np.clip(spc_rgb * 255.0, 0, 255).astype(np.uint8), mode='RGB').save(spc_png)
    convert_to_dds(spc_png, False)
    created.append(f"{base_filename}_spc.dds")

    # Normal Map
    nrm_rgb = nrm_arr[:, :, :3].copy()
    if invert_green: nrm_rgb[:, :, 1] = 255 - nrm_rgb[:, :, 1]
    if invert_blue: nrm_rgb[:, :, 2] = 255 - nrm_rgb[:, :, 2]
    
    nrm_out_png = os.path.join(save_dir, f"{base_filename}_nrm.png")
    Image.fromarray(nrm_rgb, mode='RGB').save(nrm_out_png)
    convert_to_dds(nrm_out_png, False)
    created.append(f"{base_filename}_nrm.dds")

    # LP Generation (Fallback for engine stability, uses Phong mask for Gloss)
    lp_arr = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
    lp_arr[:, :, 0] = nrm_arr[:, :, 3] 
    lp_png = os.path.join(save_dir, f"{base_filename}_lp.png")
    Image.fromarray(lp_arr, mode='RGB').save(lp_png)
    convert_to_dds(lp_png, False)
    created.append(f"{base_filename}_lp.dds")

    return created

# ==========================================
# GUI EXECUTORS
# ==========================================

def run_single_conversion(vars_dict):
    try:
        created = core_convert(
            vars_dict['base'].get(), vars_dict['met'].get(), vars_dict['rough'].get(), vars_dict['ao'].get(),
            vars_dict['use_packed'].get(), vars_dict['packed'].get(), vars_dict['emissive'].get(),
            vars_dict['nrm'].get(), vars_dict['cc'].get(), vars_dict['inv_g'].get(), vars_dict['inv_b'].get(), vars_dict['out_dir'].get()
        )
        messagebox.showinfo("Success", "Textures converted successfully!\n\nCreated:\n" + "\n".join(created))
    except Exception as e:
        messagebox.showerror("Conversion Error", str(e))

def run_single_reverse(vars_dict):
    try:
        created = core_reverse(
            vars_dict['dif'].get(), vars_dict['spc'].get(), vars_dict['lp'].get(), 
            vars_dict['nrm'].get(), vars_dict['cc'].get(), vars_dict['inv_g'].get(), vars_dict['inv_b'].get(),
            vars_dict['pack'].get(), vars_dict['out_dir'].get()
        )
        messagebox.showinfo("Success", "SM1 textures unpacked to PBR successfully!\n\nCreated:\n" + "\n".join(created))
    except Exception as e:
        messagebox.showerror("Reverse Conversion Error", str(e))

def run_single_sfm(vars_dict):
    try:
        created = core_sfm_to_sm1(
            vars_dict['dif'].get(), vars_dict['nrm'].get(), vars_dict['vmt'].get(), 
            vars_dict['out_dir'].get(), vars_dict['inv_g'].get(), vars_dict['inv_b'].get()
        )
        messagebox.showinfo("Success", "SFM assets ported to SM1 successfully!\n\nCreated:\n" + "\n".join(created))
    except Exception as e:
        messagebox.showerror("SFM Conversion Error", str(e))

def run_batch_conversion(vars_dict, mode="forward"):
    directory = vars_dict['dir'].get()
    out_dir = vars_dict['out_dir'].get()
    if not directory or not os.path.exists(directory):
        messagebox.showwarning("Error", "Please select a valid directory.")
        return

    valid_exts = ['.png', '.jpg', '.jpeg', '.tga', '.dds']
    success_count, errors = 0, []
    
    out_dir_abs = os.path.normcase(os.path.abspath(out_dir)) if out_dir else ""
    forward_outputs = ['_dif', '_spc', '_lp', '_nrm', '_cc', '_packed']
    reverse_outputs = ['_basecolor', '_metallic', '_roughness', '_normal', '_emissive', '_packed', '_cc']

    def find_map(base_name, suffix, root_dir):
        if not suffix: return ""
        actual_sfx = "" if suffix.strip().lower() == "/na/" else suffix
        for ext in valid_exts:
            p = os.path.join(root_dir, base_name + actual_sfx + ext)
            if os.path.exists(p): return p
        return ""

    for root_dir, dirs, files in os.walk(directory):
        # Do not traverse into the output directory if it is a subfolder of the input directory
        if out_dir_abs:
            dirs[:] = [d for d in dirs if os.path.normcase(os.path.abspath(os.path.join(root_dir, d))) != out_dir_abs]

        for file in files:
            name, ext = os.path.splitext(file)
            if ext.lower() not in valid_exts: continue

            if mode == "forward":
                base_sfx = vars_dict['base_sfx'].get().strip()
                actual_base_sfx = "" if base_sfx.lower() == "/na/" else base_sfx
                
                if actual_base_sfx == "":
                    known_sfx = get_known_suffixes(vars_dict, 'base_sfx')
                    # Actively ignore secondary maps and previously generated outputs
                    if any(name.lower().endswith(s.lower()) for s in known_sfx + forward_outputs): continue
                    base_name = name
                else:
                    if not name.lower().endswith(actual_base_sfx.lower()): continue
                    base_name = name[:-len(actual_base_sfx)] 
                    
                try:
                    use_packed = vars_dict.get('use_packed', tk.BooleanVar(value=False)).get()
                    p_sfx = vars_dict.get('packed_sfx', tk.StringVar(value="_Packed")).get()
                    
                    core_convert(
                        os.path.join(root_dir, file), 
                        find_map(base_name, vars_dict['met_sfx'].get(), root_dir) if not use_packed else "", 
                        find_map(base_name, vars_dict['rough_sfx'].get(), root_dir) if not use_packed else "", 
                        find_map(base_name, vars_dict['ao_sfx'].get(), root_dir) if not use_packed else "", 
                        use_packed, 
                        find_map(base_name, p_sfx, root_dir) if use_packed else "", 
                        find_map(base_name, vars_dict['emissive_sfx'].get(), root_dir), 
                        find_map(base_name, vars_dict['nrm_sfx'].get(), root_dir), 
                        find_map(base_name, vars_dict.get('cc_sfx', tk.StringVar(value="")).get(), root_dir),
                        vars_dict['inv_g'].get(), vars_dict['inv_b'].get(), out_dir
                    )
                    success_count += 1
                except Exception as e: errors.append(f"{base_name}: {str(e)}")

            elif mode == "reverse":
                dif_sfx = vars_dict['dif_sfx'].get().strip()
                actual_dif_sfx = "" if dif_sfx.lower() == "/na/" else dif_sfx
                
                if actual_dif_sfx == "":
                    known_sfx = get_known_suffixes(vars_dict, 'dif_sfx')
                    # Actively ignore secondary maps and previously generated outputs
                    if any(name.lower().endswith(s.lower()) for s in known_sfx + reverse_outputs): continue
                    base_name = name
                else:
                    if not name.lower().endswith(actual_dif_sfx.lower()): continue
                    base_name = name[:-len(actual_dif_sfx)] 
                    
                try:
                    core_reverse(
                        os.path.join(root_dir, file), 
                        find_map(base_name, vars_dict['spc_sfx'].get(), root_dir),
                        find_map(base_name, vars_dict['lp_sfx'].get(), root_dir), 
                        find_map(base_name, vars_dict['nrm_sfx'].get(), root_dir),
                        find_map(base_name, vars_dict.get('cc_sfx', tk.StringVar(value="")).get(), root_dir),
                        vars_dict['inv_g'].get(), vars_dict['inv_b'].get(), vars_dict.get('pack', tk.BooleanVar(value=False)).get(), out_dir
                    )
                    success_count += 1
                except Exception as e: errors.append(f"{base_name}: {str(e)}")

    if success_count > 0 and not errors: messagebox.showinfo("Batch Complete", f"Processed {success_count} material(s).")
    elif errors: messagebox.showerror("Batch Results", f"Processed {success_count} material(s).\nErrors:\n" + "\n".join(errors[:5]))
    else: messagebox.showinfo("Batch Complete", "No matching files found.")

def run_batch_sfm(vars_dict):
    directory = vars_dict['dir'].get()
    out_dir = vars_dict['out_dir'].get()
    if not directory or not os.path.exists(directory):
        messagebox.showwarning("Error", "Please select a valid directory.")
        return

    success_count, errors = 0, []
    out_dir_abs = os.path.normcase(os.path.abspath(out_dir)) if out_dir else ""
    
    for root_dir, dirs, files in os.walk(directory):
        # Do not traverse into the output directory
        if out_dir_abs:
            dirs[:] = [d for d in dirs if os.path.normcase(os.path.abspath(os.path.join(root_dir, d))) != out_dir_abs]

        for file in files:
            if file.lower().endswith('.vmt'):
                try:
                    core_sfm_to_sm1("", "", os.path.join(root_dir, file), out_dir, vars_dict['inv_g'].get(), vars_dict['inv_b'].get())
                    success_count += 1
                except Exception as e:
                    errors.append(f"{file}: {str(e)}")

    if success_count > 0 and not errors: messagebox.showinfo("Batch Complete", f"Processed {success_count} VMT(s).")
    elif errors: messagebox.showerror("Batch Results", f"Processed {success_count} VMT(s).\nErrors:\n" + "\n".join(errors[:5]))
    else: messagebox.showinfo("Batch Complete", "No .vmt files found in the directory.")

# ==========================================
# UI BUILDER
# ==========================================

def main():
    root = tk.Tk()
    root.title("PBR / SM1 / SFM Converter Tool")
    root.geometry("640x680") 
    root.resizable(False, False)

    notebook = ttk.Notebook(root)
    notebook.pack(expand=True, fill="both", padx=10, pady=10)

    f_s_fwd = ttk.Frame(notebook); notebook.add(f_s_fwd, text="1. PBR->SM1")
    f_b_fwd = ttk.Frame(notebook); notebook.add(f_b_fwd, text="2. Batch PBR")
    f_s_rev = ttk.Frame(notebook); notebook.add(f_s_rev, text="3. SM1->PBR")
    f_b_rev = ttk.Frame(notebook); notebook.add(f_b_rev, text="4. Batch SM1")
    f_s_sfm = ttk.Frame(notebook); notebook.add(f_s_sfm, text="5. SFM->SM1")
    f_b_sfm = ttk.Frame(notebook); notebook.add(f_b_sfm, text="6. Batch SFM")

    pad, bw = {'padx': 10, 'pady': 5}, 18

    # --- 1. SINGLE PBR TO SM1 ---
    s_vars = {'base': tk.StringVar(), 'packed': tk.StringVar(), 'met': tk.StringVar(), 'rough': tk.StringVar(), 'ao': tk.StringVar(), 'emissive': tk.StringVar(), 'nrm': tk.StringVar(), 'cc': tk.StringVar(), 'out_dir': tk.StringVar(), 'use_packed': tk.BooleanVar(value=False), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}

    tk.Button(f_s_fwd, text="Base Color", width=bw, command=lambda: browse_file(s_vars['base'], "Select Base Color")).grid(row=0, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['base'], width=50, state='readonly').grid(row=0, column=1, **pad)
    tk.Checkbutton(f_s_fwd, text="Use Packed Texture (R=Met, G=Rough, B=AO)", variable=s_vars['use_packed'], font=("Arial", 9, "bold")).grid(row=1, column=0, columnspan=2, pady=(5, 0), sticky="w", padx=10)
    
    btn_packed = tk.Button(f_s_fwd, text="Packed (R,G,B)", width=bw, command=lambda: browse_file(s_vars['packed'], "Select Packed"))
    btn_packed.grid(row=2, column=0, **pad); ent_packed = tk.Entry(f_s_fwd, textvariable=s_vars['packed'], width=50); ent_packed.grid(row=2, column=1, **pad)
    
    btn_met = tk.Button(f_s_fwd, text="Metallic", width=bw, command=lambda: browse_file(s_vars['met'], "Select Metallic"))
    btn_met.grid(row=3, column=0, **pad); ent_met = tk.Entry(f_s_fwd, textvariable=s_vars['met'], width=50); ent_met.grid(row=3, column=1, **pad)
    
    btn_rough = tk.Button(f_s_fwd, text="Roughness", width=bw, command=lambda: browse_file(s_vars['rough'], "Select Roughness"))
    btn_rough.grid(row=4, column=0, **pad); ent_rough = tk.Entry(f_s_fwd, textvariable=s_vars['rough'], width=50); ent_rough.grid(row=4, column=1, **pad)
    
    tk.Button(f_s_fwd, text="AO (Opt)", width=bw, command=lambda: browse_file(s_vars['ao'], "Select AO")).grid(row=5, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['ao'], width=50, state='readonly').grid(row=5, column=1, **pad)
    tk.Button(f_s_fwd, text="Emissive (Opt)", width=bw, command=lambda: browse_file(s_vars['emissive'], "Select Emissive")).grid(row=6, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['emissive'], width=50, state='readonly').grid(row=6, column=1, **pad)
    tk.Button(f_s_fwd, text="Normal (Opt)", width=bw, command=lambda: browse_file(s_vars['nrm'], "Select Normal Map")).grid(row=7, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['nrm'], width=50, state='readonly').grid(row=7, column=1, **pad)
    tk.Button(f_s_fwd, text="CC Map (Opt)", width=bw, command=lambda: browse_file(s_vars['cc'], "Select CC Map")).grid(row=8, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['cc'], width=50, state='readonly').grid(row=8, column=1, **pad)
    tk.Button(f_s_fwd, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(s_vars['out_dir'], "Select Dir")).grid(row=9, column=0, **pad)
    tk.Entry(f_s_fwd, textvariable=s_vars['out_dir'], width=50, state='readonly').grid(row=9, column=1, **pad)

    opts = tk.Frame(f_s_fwd); opts.grid(row=10, column=1, sticky="w", padx=5)
    tk.Checkbutton(opts, text="Invert Green", variable=s_vars['inv_g']).pack(side="left")
    tk.Checkbutton(opts, text="Invert Blue", variable=s_vars['inv_b']).pack(side="left", padx=10)
    
    def toggle_single(*args):
        sp, si = ('normal', 'disabled') if s_vars['use_packed'].get() else ('disabled', 'normal')
        btn_packed.config(state=sp); ent_packed.config(state='readonly' if sp=='normal' else 'disabled')
        btn_met.config(state=si); ent_met.config(state='readonly' if si=='normal' else 'disabled')
        btn_rough.config(state=si); ent_rough.config(state='readonly' if si=='normal' else 'disabled')
    s_vars['use_packed'].trace_add("write", toggle_single); toggle_single()
    
    tk.Button(f_s_fwd, text="CONVERT TO SM1", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), command=lambda: run_single_conversion(s_vars)).grid(row=11, column=0, columnspan=2, pady=10, ipadx=10, ipady=5)

    # --- 2. BATCH PBR TO SM1 ---
    bf_vars = {'dir': tk.StringVar(), 'out_dir': tk.StringVar(), 'base_sfx': tk.StringVar(value="_BaseColor"), 'packed_sfx': tk.StringVar(value="_Packed"), 'met_sfx': tk.StringVar(value="_Metallic"), 'rough_sfx': tk.StringVar(value="_Roughness"), 'ao_sfx': tk.StringVar(value="_AO"), 'emissive_sfx': tk.StringVar(value="_Emissive"), 'nrm_sfx': tk.StringVar(value="_Normal"), 'cc_sfx': tk.StringVar(value="_CC"), 'use_packed': tk.BooleanVar(value=False), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}
    tk.Label(f_b_fwd, text="Select folder to process all PBR files into SM1.\nSet a suffix to '/na/' to select files without suffixes.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(f_b_fwd, text="Input Directory", width=bw, command=lambda: browse_directory(bf_vars['dir'], "Select Dir")).grid(row=1, column=0, **pad)
    tk.Entry(f_b_fwd, textvariable=bf_vars['dir'], width=50, state='readonly').grid(row=1, column=1, **pad)
    tk.Button(f_b_fwd, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(bf_vars['out_dir'], "Select Output Dir")).grid(row=2, column=0, **pad)
    tk.Entry(f_b_fwd, textvariable=bf_vars['out_dir'], width=50, state='readonly').grid(row=2, column=1, **pad)
    
    tk.Checkbutton(f_b_fwd, text="Use Packed Textures (R=Met, G=Rough, B=AO)", variable=bf_vars['use_packed'], font=("Arial", 9, "bold")).grid(row=3, column=0, columnspan=2, pady=(5, 0), sticky="w", padx=10)

    labels = ["Base Color Suffix:", "Packed Suffix:", "Metallic Suffix:", "Roughness Suffix:", "Normal Suffix:", "AO Suffix (Opt):", "Emissive Suffix (Opt):", "CC Suffix (Opt):"]
    vars_list = ['base_sfx', 'packed_sfx', 'met_sfx', 'rough_sfx', 'nrm_sfx', 'ao_sfx', 'emissive_sfx', 'cc_sfx']
    
    ent_dict = {}
    for i, (l, v) in enumerate(zip(labels, vars_list)):
        tk.Label(f_b_fwd, text=l).grid(row=4+i, column=0, sticky="e", **pad)
        ent = tk.Entry(f_b_fwd, textvariable=bf_vars[v], width=30)
        ent.grid(row=4+i, column=1, sticky="w", **pad)
        ent_dict[v] = ent
        
    def toggle_batch_fwd(*args):
        sp, si = ('normal', 'disabled') if bf_vars['use_packed'].get() else ('disabled', 'normal')
        ent_dict['packed_sfx'].config(state=sp)
        ent_dict['met_sfx'].config(state=si)
        ent_dict['rough_sfx'].config(state=si)
        ent_dict['ao_sfx'].config(state=si)
    bf_vars['use_packed'].trace_add("write", toggle_batch_fwd); toggle_batch_fwd()

    bf_opts = tk.Frame(f_b_fwd); bf_opts.grid(row=12, column=1, sticky="w", padx=5, pady=5)
    tk.Checkbutton(bf_opts, text="Invert Green", variable=bf_vars['inv_g']).pack(side="left")
    tk.Checkbutton(bf_opts, text="Invert Blue", variable=bf_vars['inv_b']).pack(side="left", padx=10)
    tk.Button(f_b_fwd, text="START BATCH", bg="#2196F3", fg="white", font=("Arial", 10, "bold"), command=lambda: run_batch_conversion(bf_vars, "forward")).grid(row=13, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- 3. SINGLE SM1 TO PBR ---
    sr_vars = {'dif': tk.StringVar(), 'spc': tk.StringVar(), 'lp': tk.StringVar(), 'nrm': tk.StringVar(), 'cc': tk.StringVar(), 'out_dir': tk.StringVar(), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False), 'pack': tk.BooleanVar(value=False)}
    tk.Label(f_s_rev, text="Unpack SM1 DDS/PNG textures back to PBR PNGs.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(f_s_rev, text="Diffuse (_dif)", width=bw, command=lambda: browse_file(sr_vars['dif'], "Select Diffuse")).grid(row=1, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['dif'], width=50, state='readonly').grid(row=1, column=1, **pad)
    tk.Button(f_s_rev, text="Specular (_spc)", width=bw, command=lambda: browse_file(sr_vars['spc'], "Select Specular")).grid(row=2, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['spc'], width=50, state='readonly').grid(row=2, column=1, **pad)
    tk.Button(f_s_rev, text="LP / Gloss (_lp)", width=bw, command=lambda: browse_file(sr_vars['lp'], "Select LP Map")).grid(row=3, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['lp'], width=50, state='readonly').grid(row=3, column=1, **pad)
    tk.Button(f_s_rev, text="Normal Map (Opt)", width=bw, command=lambda: browse_file(sr_vars['nrm'], "Select Normal Map")).grid(row=4, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['nrm'], width=50, state='readonly').grid(row=4, column=1, **pad)
    tk.Button(f_s_rev, text="CC Map (Opt)", width=bw, command=lambda: browse_file(sr_vars['cc'], "Select CC Map")).grid(row=5, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['cc'], width=50, state='readonly').grid(row=5, column=1, **pad)
    tk.Button(f_s_rev, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(sr_vars['out_dir'], "Select Dir")).grid(row=6, column=0, **pad)
    tk.Entry(f_s_rev, textvariable=sr_vars['out_dir'], width=50, state='readonly').grid(row=6, column=1, **pad)
    
    sr_opts = tk.Frame(f_s_rev); sr_opts.grid(row=7, column=1, sticky="w", padx=5, pady=(10, 0))
    tk.Checkbutton(sr_opts, text="Invert Green", variable=sr_vars['inv_g']).pack(side="left")
    tk.Checkbutton(sr_opts, text="Invert Blue", variable=sr_vars['inv_b']).pack(side="left", padx=10)
    sr_pack_opts = tk.Frame(f_s_rev); sr_pack_opts.grid(row=8, column=1, sticky="w", padx=5, pady=(5, 10))
    tk.Checkbutton(sr_pack_opts, text="Export Packed Texture (R=Met, G=Rough, B=White)", variable=sr_vars['pack'], font=("Arial", 9, "bold")).pack(side="left")
    tk.Button(f_s_rev, text="REVERSE TO PBR", bg="#E91E63", fg="white", font=("Arial", 10, "bold"), command=lambda: run_single_reverse(sr_vars)).grid(row=9, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- 4. BATCH SM1 TO PBR ---
    br_vars = {'dir': tk.StringVar(), 'out_dir': tk.StringVar(), 'dif_sfx': tk.StringVar(value="_dif"), 'spc_sfx': tk.StringVar(value="_spc"), 'lp_sfx': tk.StringVar(value="_lp"), 'nrm_sfx': tk.StringVar(value="_nrm"), 'cc_sfx': tk.StringVar(value="_cc"), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False), 'pack': tk.BooleanVar(value=False)}
    tk.Label(f_b_rev, text="Select folder to unpack SM1 Textures back into PBR.\nSet a suffix to '/na/' to select files without suffixes.").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(f_b_rev, text="Input Directory", width=bw, command=lambda: browse_directory(br_vars['dir'], "Select Dir")).grid(row=1, column=0, **pad)
    tk.Entry(f_b_rev, textvariable=br_vars['dir'], width=50, state='readonly').grid(row=1, column=1, **pad)
    tk.Button(f_b_rev, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(br_vars['out_dir'], "Select Dir")).grid(row=2, column=0, **pad)
    tk.Entry(f_b_rev, textvariable=br_vars['out_dir'], width=50, state='readonly').grid(row=2, column=1, **pad)
    
    for i, (l, v) in enumerate(zip(["Diffuse Suffix:", "Specular Suffix:", "LP / Gloss Suffix:", "Normal Suffix:", "CC Suffix (Opt):"], ['dif_sfx', 'spc_sfx', 'lp_sfx', 'nrm_sfx', 'cc_sfx'])):
        tk.Label(f_b_rev, text=l).grid(row=3+i, column=0, sticky="e", **pad)
        tk.Entry(f_b_rev, textvariable=br_vars[v], width=30).grid(row=3+i, column=1, sticky="w", **pad)
        
    br_opts = tk.Frame(f_b_rev); br_opts.grid(row=8, column=1, sticky="w", padx=5, pady=(10, 0))
    tk.Checkbutton(br_opts, text="Invert Green", variable=br_vars['inv_g']).pack(side="left")
    tk.Checkbutton(br_opts, text="Invert Blue", variable=br_vars['inv_b']).pack(side="left", padx=10)
    br_pack_opts = tk.Frame(f_b_rev); br_pack_opts.grid(row=9, column=1, sticky="w", padx=5, pady=(5, 10))
    tk.Checkbutton(br_pack_opts, text="Export Packed Textures (R=Met, G=Rough, B=White)", variable=br_vars['pack'], font=("Arial", 9, "bold")).pack(side="left")
    tk.Button(f_b_rev, text="REVERSE BATCH", bg="#E91E63", fg="white", font=("Arial", 10, "bold"), command=lambda: run_batch_conversion(br_vars, "reverse")).grid(row=10, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- 5. SINGLE SFM TO SM1 ---
    sfm_vars = {'dif': tk.StringVar(), 'nrm': tk.StringVar(), 'vmt': tk.StringVar(), 'out_dir': tk.StringVar(), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}
    tk.Label(f_s_sfm, text="Convert SFM textures to SM1 format.\nSelect individual files OR use a .vmt material file.", justify="left").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(f_s_sfm, text="Diffuse Map", width=bw, command=lambda: browse_file(sfm_vars['dif'], "Select SFM Diffuse")).grid(row=1, column=0, **pad)
    tk.Entry(f_s_sfm, textvariable=sfm_vars['dif'], width=50, state='readonly').grid(row=1, column=1, **pad)
    tk.Button(f_s_sfm, text="Normal Map", width=bw, command=lambda: browse_file(sfm_vars['nrm'], "Select SFM Normal")).grid(row=2, column=0, **pad)
    tk.Entry(f_s_sfm, textvariable=sfm_vars['nrm'], width=50, state='readonly').grid(row=2, column=1, **pad)
    
    ttk.Separator(f_s_sfm, orient="horizontal").grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)
    
    tk.Button(f_s_sfm, text="VMT Material (Opt)", width=bw, command=lambda: browse_file(sfm_vars['vmt'], "Select VMT", True)).grid(row=4, column=0, **pad)
    tk.Entry(f_s_sfm, textvariable=sfm_vars['vmt'], width=50, state='readonly').grid(row=4, column=1, **pad)
    
    tk.Button(f_s_sfm, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(sfm_vars['out_dir'], "Select Dir")).grid(row=5, column=0, **pad)
    tk.Entry(f_s_sfm, textvariable=sfm_vars['out_dir'], width=50, state='readonly').grid(row=5, column=1, **pad)
    
    sfm_opts = tk.Frame(f_s_sfm); sfm_opts.grid(row=6, column=1, sticky="w", padx=5, pady=10)
    tk.Checkbutton(sfm_opts, text="Invert Green", variable=sfm_vars['inv_g']).pack(side="left")
    tk.Checkbutton(sfm_opts, text="Invert Blue", variable=sfm_vars['inv_b']).pack(side="left", padx=10)
    tk.Button(f_s_sfm, text="CONVERT TO SM1", bg="#FF9800", fg="white", font=("Arial", 10, "bold"), command=lambda: run_single_sfm(sfm_vars)).grid(row=7, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    # --- 6. BATCH SFM TO SM1 ---
    bsfm_vars = {'dir': tk.StringVar(), 'out_dir': tk.StringVar(), 'inv_g': tk.BooleanVar(value=True), 'inv_b': tk.BooleanVar(value=False)}
    tk.Label(f_b_sfm, text="Batch convert SFM VMT materials to SM1.\nSelect a folder containing .vmt files.", justify="left").grid(row=0, column=0, columnspan=2, pady=10, padx=10, sticky="w")
    tk.Button(f_b_sfm, text="VMT Directory", width=bw, command=lambda: browse_directory(bsfm_vars['dir'], "Select Dir")).grid(row=1, column=0, **pad)
    tk.Entry(f_b_sfm, textvariable=bsfm_vars['dir'], width=50, state='readonly').grid(row=1, column=1, **pad)
    tk.Button(f_b_sfm, text="Output Dir (Opt)", width=bw, command=lambda: browse_directory(bsfm_vars['out_dir'], "Select Dir")).grid(row=2, column=0, **pad)
    tk.Entry(f_b_sfm, textvariable=bsfm_vars['out_dir'], width=50, state='readonly').grid(row=2, column=1, **pad)
    
    bsfm_opts = tk.Frame(f_b_sfm); bsfm_opts.grid(row=3, column=1, sticky="w", padx=5, pady=10)
    tk.Checkbutton(bsfm_opts, text="Invert Green", variable=bsfm_vars['inv_g']).pack(side="left")
    tk.Checkbutton(bsfm_opts, text="Invert Blue", variable=bsfm_vars['inv_b']).pack(side="left", padx=10)
    tk.Button(f_b_sfm, text="BATCH CONVERT SFM", bg="#FF9800", fg="white", font=("Arial", 10, "bold"), command=lambda: run_batch_sfm(bsfm_vars)).grid(row=4, column=0, columnspan=2, pady=15, ipadx=10, ipady=5)

    root.mainloop()

if __name__ == "__main__":
    main()