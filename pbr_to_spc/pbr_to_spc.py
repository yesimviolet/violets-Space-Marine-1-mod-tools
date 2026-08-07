import tkinter as tk
from tkinter import filedialog, messagebox
import numpy as np
from PIL import Image
import os
import subprocess
import sys

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
    
    # DXT1 = BC1_UNORM, DXT5 = BC3_UNORM
    format_str = "BC3_UNORM" if has_alpha else "BC1_UNORM"
    save_dir = os.path.dirname(png_path)

    cmd = [
        texconv_path,
        "-f", format_str,
        "-y",               
        "-o", save_dir,     
        png_path
    ]

    subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    
    if os.path.exists(png_path):
        os.remove(png_path)

def browse_file(string_var, title):
    filepath = filedialog.askopenfilename(
        title=title,
        filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif"), ("All Files", "*.*")]
    )
    if filepath:
        string_var.set(filepath)

def convert_textures(base_path, met_path, rough_path, ao_path, use_packed, packed_path, emissive_path, cc_path, nrm_path, invert_green, invert_blue):
    texconv_path = os.path.join(get_script_dir(), "texconv.exe")
    if not os.path.exists(texconv_path):
        messagebox.showwarning("Missing texconv.exe", 
                               "Please download 'texconv.exe' (Microsoft DirectXTex) and place it in the same folder as this tool to enable DDS compression.")
        return

    if not base_path:
        messagebox.showwarning("Missing Files", "Please select a Base Color texture!")
        return

    if use_packed and not packed_path:
        messagebox.showwarning("Missing Files", "Please select your Packed Texture!")
        return
    elif not use_packed and not (met_path and rough_path):
        messagebox.showwarning("Missing Files", "Please select Metallic and Roughness textures!")
        return

    try:
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
            # --- PACKED MODE ---
            img_packed = Image.open(packed_path).convert('RGB')
            if img_packed.size != target_size:
                img_packed = img_packed.resize(target_size)
            
            packed_data = np.array(img_packed)
            metallic = packed_data[:, :, 0].astype(np.float32) / 255.0
            roughness = packed_data[:, :, 1]  
            ao = packed_data[:, :, 2].astype(np.float32) / 255.0
            
        else:
            # --- INDIVIDUAL MAPS MODE ---
            img_met = Image.open(met_path).convert('L')
            img_rough = Image.open(rough_path).convert('L')
            
            if img_met.size != target_size:
                img_met = img_met.resize(target_size)
            if img_rough.size != target_size:
                img_rough = img_rough.resize(target_size)
                
            metallic = np.array(img_met).astype(np.float32) / 255.0
            roughness = np.array(img_rough)
            
            if ao_path and os.path.exists(ao_path):
                img_ao = Image.open(ao_path).convert('L')
                if img_ao.size != target_size:
                    img_ao = img_ao.resize(target_size)
            else:
                img_ao = Image.new('L', target_size, 255) 
                
            ao = np.array(img_ao).astype(np.float32) / 255.0

        metallic_3c = np.stack((metallic,)*3, axis=-1)
        ao_3c = np.stack((ao,)*3, axis=-1)

        # 1. Legacy Diffuse (_dif)
        diffuse = base_color * (1.0 - metallic_3c) * ao_3c
        diffuse_rgb = np.clip(diffuse * 255.0, 0, 255).astype(np.uint8)
        
        if has_transparency:
            diffuse_rgba = np.dstack((diffuse_rgb, alpha_array))
            diffuse_img = Image.fromarray(diffuse_rgba, mode='RGBA')
        else:
            diffuse_img = Image.fromarray(diffuse_rgb, mode='RGB')
            
        diffuse_img.save(diffuse_png)

        # 2. Specular Color (_spc)
        dielectric_base = np.full_like(base_color, 0.22)
        specular = (base_color * metallic_3c) + (dielectric_base * (1.0 - metallic_3c))
        specular_with_ao = specular * ao_3c
        specular_img = Image.fromarray(np.clip(specular_with_ao * 255.0, 0, 255).astype(np.uint8))
        specular_img.save(specular_png)

        # 3. Glossiness / LP map (_lp)
        gloss_val = np.clip(255 - roughness, 0, 255).astype(np.uint8)
        
        if emissive_path and os.path.exists(emissive_path):
            img_emissive = Image.open(emissive_path).convert('L')
            if img_emissive.size != target_size:
                img_emissive = img_emissive.resize(target_size)
            emissive_val = np.array(img_emissive)
        else:
            emissive_val = np.zeros_like(gloss_val)
            
        if cc_path and os.path.exists(cc_path):
            img_cc = Image.open(cc_path).convert('RGB')
            if img_cc.size != target_size:
                img_cc = img_cc.resize(target_size)
            cc_val = np.array(img_cc)[:, :, 2]
        else:
            cc_val = np.zeros_like(gloss_val)

        lp_array = np.stack((gloss_val, emissive_val, cc_val), axis=-1)
        lp_img = Image.fromarray(lp_array, mode='RGB')
        lp_img.save(lp_png)

        # Convert Main Maps to DDS
        convert_to_dds(diffuse_png, has_transparency)  
        convert_to_dds(specular_png, False)            
        convert_to_dds(lp_png, False)                  

        created_files = [f"{base_filename}_dif.dds", f"{base_filename}_spc.dds", f"{base_filename}_lp.dds"]

        # 4. Normal Map Processing (_nrm)
        if nrm_path and os.path.exists(nrm_path):
            nrm_png = os.path.join(save_dir, f"{base_filename}_nrm.png")
            img_nrm = Image.open(nrm_path).convert('RGB')
            if img_nrm.size != target_size:
                img_nrm = img_nrm.resize(target_size)
            
            nrm_array = np.array(img_nrm)
            
            # Invert Green Channel (Y)
            if invert_green:
                nrm_array[:, :, 1] = 255 - nrm_array[:, :, 1]
            
            # Invert Blue Channel (Z)
            if invert_blue:
                nrm_array[:, :, 2] = 255 - nrm_array[:, :, 2]
                
            Image.fromarray(nrm_array).save(nrm_png)
            convert_to_dds(nrm_png, False)
            created_files.append(f"{base_filename}_nrm.dds")

        msg = "DDS Textures converted successfully!\n\nCreated:\n" + "\n".join(created_files)
        messagebox.showinfo("Success", msg)

    except Exception as e:
        messagebox.showerror("Error", f"An error occurred during conversion:\n{str(e)}")


def main():
    root = tk.Tk()
    root.title("PBR Space Marine 1 Texture Converter (DDS)")
    root.geometry("540x470") 
    root.resizable(False, False)

    base_var = tk.StringVar()
    packed_var = tk.StringVar()
    met_var = tk.StringVar()
    rough_var = tk.StringVar()
    ao_var = tk.StringVar()
    emissive_var = tk.StringVar()
    cc_var = tk.StringVar()
    nrm_var = tk.StringVar()
    
    use_packed_var = tk.BooleanVar(value=False)
    invert_green_var = tk.BooleanVar(value=True) # Defaults to True (OpenGL -> DirectX)
    invert_blue_var = tk.BooleanVar(value=False) # Defaults to False

    padding = {'padx': 10, 'pady': 5}
    btn_width = 17

    tk.Button(root, text="Base Color", width=btn_width, command=lambda: browse_file(base_var, "Select Base Color")).grid(row=0, column=0, **padding)
    tk.Entry(root, textvariable=base_var, width=50, state='readonly').grid(row=0, column=1, **padding)

    chk_packed = tk.Checkbutton(root, text="Use Packed Texture (R=Metallic, G=Roughness, B=AO)", variable=use_packed_var, font=("Arial", 9, "bold"))
    chk_packed.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky="w", padx=10)

    btn_packed = tk.Button(root, text="Packed (R,G,B)", width=btn_width, command=lambda: browse_file(packed_var, "Select Packed Texture"))
    btn_packed.grid(row=2, column=0, **padding)
    ent_packed = tk.Entry(root, textvariable=packed_var, width=50)
    ent_packed.grid(row=2, column=1, **padding)

    btn_met = tk.Button(root, text="Metallic", width=btn_width, command=lambda: browse_file(met_var, "Select Metallic"))
    btn_met.grid(row=3, column=0, **padding)
    ent_met = tk.Entry(root, textvariable=met_var, width=50)
    ent_met.grid(row=3, column=1, **padding)

    btn_rough = tk.Button(root, text="Roughness", width=btn_width, command=lambda: browse_file(rough_var, "Select Roughness"))
    btn_rough.grid(row=4, column=0, **padding)
    ent_rough = tk.Entry(root, textvariable=rough_var, width=50)
    ent_rough.grid(row=4, column=1, **padding)

    btn_ao = tk.Button(root, text="AO (Optional)", width=btn_width, command=lambda: browse_file(ao_var, "Select Ambient Occlusion"))
    btn_ao.grid(row=5, column=0, **padding)
    ent_ao = tk.Entry(root, textvariable=ao_var, width=50)
    ent_ao.grid(row=5, column=1, **padding)

    btn_emissive = tk.Button(root, text="Emissive (Optional)", width=btn_width, command=lambda: browse_file(emissive_var, "Select Emissive Texture"))
    btn_emissive.grid(row=6, column=0, **padding)
    ent_emissive = tk.Entry(root, textvariable=emissive_var, width=50)
    ent_emissive.grid(row=6, column=1, **padding)

    btn_cc = tk.Button(root, text="SM2 CC (Optional)", width=btn_width, command=lambda: browse_file(cc_var, "Select SM2 CC Texture"))
    btn_cc.grid(row=7, column=0, **padding)
    ent_cc = tk.Entry(root, textvariable=cc_var, width=50)
    ent_cc.grid(row=7, column=1, **padding)

    btn_nrm = tk.Button(root, text="Normal Map (Optional)", width=btn_width, command=lambda: browse_file(nrm_var, "Select Normal Map"))
    btn_nrm.grid(row=8, column=0, **padding)
    ent_nrm = tk.Entry(root, textvariable=nrm_var, width=50)
    ent_nrm.grid(row=8, column=1, **padding)
    
    # --- Checkboxes for Normal Map Channels in a sub-frame ---
    nrm_options_frame = tk.Frame(root)
    nrm_options_frame.grid(row=9, column=1, sticky="w", padx=5)
    
    chk_invert_g = tk.Checkbutton(nrm_options_frame, text="Invert Green (Y)", variable=invert_green_var, font=("Arial", 9))
    chk_invert_g.pack(side="left")
    
    chk_invert_b = tk.Checkbutton(nrm_options_frame, text="Invert Blue (Z)", variable=invert_blue_var, font=("Arial", 9))
    chk_invert_b.pack(side="left", padx=10)

    def toggle_mode(*args):
        if use_packed_var.get():
            btn_packed.config(state='normal')
            ent_packed.config(state='readonly')
            btn_met.config(state='disabled')
            ent_met.config(state='disabled')
            btn_rough.config(state='disabled')
            ent_rough.config(state='disabled')
            btn_ao.config(state='disabled')
            ent_ao.config(state='disabled')
        else:
            btn_packed.config(state='disabled')
            ent_packed.config(state='disabled')
            btn_met.config(state='normal')
            ent_met.config(state='readonly')
            btn_rough.config(state='normal')
            ent_rough.config(state='readonly')
            btn_ao.config(state='normal')
            ent_ao.config(state='readonly')

    use_packed_var.trace_add("write", toggle_mode)
    toggle_mode() 

    convert_btn = tk.Button(root, text="CONVERT TO DDS", bg="#4CAF50", fg="white", font=("Arial", 10, "bold"),
                            command=lambda: convert_textures(base_var.get(), met_var.get(), rough_var.get(), ao_var.get(), 
                                                             use_packed_var.get(), packed_var.get(), emissive_var.get(), cc_var.get(), 
                                                             nrm_var.get(), invert_green_var.get(), invert_blue_var.get()))
    convert_btn.grid(row=10, column=0, columnspan=2, pady=10, ipadx=10, ipady=5)

    root.mainloop()

if __name__ == "__main__":
    main()