import os ,io ,shutil ,threading ,hashlib ,sqlite3 ,time 
import psutil 
from pathlib import Path 
from collections import defaultdict 
from datetime import datetime 

import tkinter as tk 
from tkinter import ttk ,filedialog ,messagebox ,scrolledtext 

import numpy as np 
from PIL import Image ,ImageChops ,ImageTk 
import cv2 
import imagehash 

try :
    from tkinterdnd2 import TkinterDnD ,DND_FILES 
    DND_AVAILABLE =True 
except ImportError :
    DND_AVAILABLE =False 

BG ="#F8F9FA"
SURF_LOW ="#F3F4F5"
SURF ="#EDEEEF"
SURF_HIGH ="#E7E8E9"
SURF_HIGEST ="#E1E3E4"
SURF_LOWEST ="#FFFFFF"

PRIMARY ="#005DAC"
PRIMARY_CTR ="#1976D2"
PRIMARY_FXD ="#D4E3FF"
SEC_CTR ="#BAD3FD"
ERR ="#BA1A1A"
ERR_CTR ="#FFDAD6"

ON_SURF ="#191C1D"
ON_SURF_VAR ="#414752"
OUTLINE ="#717783"
OUTLINE_VAR ="#C1C6D4"

BADGE_OK ={"bg":PRIMARY_FXD ,"fg":"#001C3A"}
BADGE_ERR ={"bg":ERR_CTR ,"fg":"#93000A"}
BADGE_WARN ={"bg":SEC_CTR ,"fg":"#2F486A"}

FONT ="Segoe UI"
MONO ="Consolas"

AppBase =TkinterDnD .Tk if DND_AVAILABLE else tk .Tk 

DB_DIR =Path .home ()/".image_inspector"
DB_PATH =DB_DIR /"history.db"

def init_db ():
    DB_DIR .mkdir (exist_ok =True )
    con =sqlite3 .connect (DB_PATH )
    con .execute ("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, filepath TEXT, analysed_at TEXT,
            mode TEXT, verdict TEXT,
            ela_score REAL, noise_score REAL, cm_score REAL,
            overall REAL, destination TEXT
        )
    """)
    con .commit ();con .close ()

def save_to_db (records ):
    con =sqlite3 .connect (DB_PATH );cur =con .cursor ()
    for r in records :
        cur .execute (
        "INSERT INTO history (filename,filepath,analysed_at,mode,verdict,"
        "ela_score,noise_score,cm_score,overall,destination) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (r .get ("filename",""),r .get ("filepath",""),
        datetime .now ().strftime ("%Y-%m-%d %H:%M:%S"),
        r .get ("mode",""),r .get ("verdict",""),
        r .get ("ela_score",0 ),r .get ("noise_score",0 ),
        r .get ("cm_score",0 ),r .get ("overall",0 ),
        r .get ("destination","")))
    con .commit ();con .close ()

def fetch_history (search =""):
    con =sqlite3 .connect (DB_PATH );cur =con .cursor ()
    if search :
        cur .execute ("SELECT * FROM history WHERE filename LIKE ? OR verdict LIKE ?"
        " ORDER BY id DESC LIMIT 500",
        (f"%{search }%",f"%{search }%"))
    else :
        cur .execute ("SELECT * FROM history ORDER BY id DESC LIMIT 500")
    rows =cur .fetchall ();con .close ()
    return rows 

def clear_history ():
    con =sqlite3 .connect (DB_PATH )
    con .execute ("DELETE FROM history");con .commit ();con .close ()

def ela_analysis (img_path ,quality =90 ):
    try :
        original =Image .open (img_path ).convert ("RGB")
        buf =io .BytesIO ()
        original .save (buf ,format ="JPEG",quality =quality );buf .seek (0 )
        recomp =Image .open (buf ).convert ("RGB")
        ela_img =ImageChops .difference (original ,recomp )
        arr =np .array (ela_img )
        mean_v ,std_v =arr .mean (),arr .std ()
        score =min (100 ,int ((mean_v /255 )*1000 +std_v *0.5 ))
        return score ,round (mean_v ,2 ),round (std_v ,2 ),ela_img 
    except :return 0 ,0 ,0 ,None 

def make_ela_heatmap (ela_pil ,original_pil ):
    arr =np .array (ela_pil .convert ("RGB"))
    gray =arr .mean (axis =2 ).astype (np .float32 )
    mn ,mx =gray .min (),gray .max ()
    if mx -mn <1 :mx =mn +1 
    norm =((gray -mn )/(mx -mn )*255 ).astype (np .uint8 )
    rgb =np .stack ([norm ,(255 -norm ),np .zeros_like (norm )],axis =2 ).astype (np .uint8 )
    return Image .fromarray (rgb ,"RGB").resize (original_pil .size ,Image .LANCZOS )

def metadata_analysis (img_path ):
    flags ,info =[],{}
    try :
        img =Image .open (img_path )
        exif_raw =img ._getexif ()if hasattr (img ,"_getexif")else None 
        TAGS ={271 :"Make",272 :"Model",305 :"Software",306 :"DateTime",36867 :"DateTimeOriginal"}
        edit_sw =["photoshop","gimp","lightroom","paint","snapseed",
        "facetune","canva","pixlr","affinity","capture one"]
        if exif_raw :
            for tid ,val in exif_raw .items ():
                name =TAGS .get (tid )
                if name :info [name ]=str (val )
            sw =info .get ("Software","").lower ()
            for s in edit_sw :
                if s in sw :flags .append (f"Editing software: '{info ['Software']}'")
            orig ,modif =info .get ("DateTimeOriginal",""),info .get ("DateTime","")
            if orig and modif and orig !=modif :
                flags .append (f"Modified after capture ({orig } → {modif })")
            if not info .get ("Make")and not info .get ("Model"):
                flags .append ("No camera make/model in EXIF")
        else :
            flags .append ("No EXIF metadata — possibly stripped after editing")
            info ["Note"]="No EXIF data"
    except Exception as e :flags .append (f"Metadata error: {e }")
    return flags ,info 

def noise_analysis (img_path ):
    try :
        img =cv2 .imread (str (img_path ))
        gray =cv2 .cvtColor (img ,cv2 .COLOR_BGR2GRAY ).astype (np .float32 )
        h ,w =gray .shape ;block =64 ;vals =[]
        for y in range (0 ,h -block ,block ):
            for x in range (0 ,w -block ,block ):
                patch =gray [y :y +block ,x :x +block ]
                vals .append ((patch -cv2 .GaussianBlur (patch ,(3 ,3 ),0 )).std ())
        if not vals :return 0 ,"Too small"
        mn ,sd =np .mean (vals ),np .std (vals )
        cv =(sd /mn *100 )if mn >0 else 0 
        score =min (100 ,int (cv *2 ))
        desc =("Uniform — natural"if cv <25 else 
        "Moderate variation"if cv <50 else 
        "High inconsistency — possible splice")
        return score ,desc 
    except Exception as e :return 0 ,f"Error: {e }"

def copy_move_detection (img_path ):
    try :
        img =cv2 .imread (str (img_path ))
        gray =cv2 .cvtColor (img ,cv2 .COLOR_BGR2GRAY )
        orb =cv2 .ORB_create (nfeatures =500 )
        kp ,des =orb .detectAndCompute (gray ,None )
        if des is None or len (kp )<10 :return 0 ,"Not enough features"
        bf =cv2 .BFMatcher (cv2 .NORM_HAMMING ,crossCheck =True )
        sus =[m for m in bf .match (des ,des )
        if 0 <m .distance <30 and m .queryIdx !=m .trainIdx ]
        score =min (100 ,len (sus )*5 )
        desc =("No copy-move detected"if score <20 else 
        f"Possible copy-move ({len (sus )} suspect pairs)")
        return score ,desc 
    except Exception as e :return 0 ,f"Error: {e }"

def analyse_tampering (img_path ,stop_flag =None ):
    """
    Runs all 4 checks. Accepts an optional threading.Event stop_flag.
    If stop_flag is set at any point, raises InterruptedError immediately.
    """
    def check_stop ():
        if stop_flag and stop_flag .is_set ():
            raise InterruptedError ("Stopped by user")

    r ={}
    check_stop ()
    es ,em ,estd ,eimg =ela_analysis (img_path )
    r ["ela"]={"score":es ,"mean":em ,"std":estd ,"image":eimg }

    check_stop ()
    mf ,mi =metadata_analysis (img_path )
    r ["metadata"]={"flags":mf ,"info":mi }

    check_stop ()
    ns ,nd =noise_analysis (img_path )
    r ["noise"]={"score":ns ,"desc":nd }

    check_stop ()
    cs ,cd =copy_move_detection (img_path )
    r ["copy_move"]={"score":cs ,"desc":cd }

    combined =min (100 ,es *0.4 +ns *0.3 +cs *0.2 +len (mf )*10 *0.1 )
    r ["overall"]=combined 
    r ["verdict"]=("LIKELY AUTHENTIC"if combined <25 else 
    "POSSIBLY EDITED"if combined <50 else 
    "LIKELY TAMPERED")
    return r 

def check_blur (p ,t =80 ):
    try :s =cv2 .Laplacian (cv2 .imread (str (p ),cv2 .IMREAD_GRAYSCALE ),cv2 .CV_64F ).var ();return s ,s <t 
    except :return 0 ,True 

def check_noise (p ,t =15 ):
    try :
        img =cv2 .imread (str (p ),cv2 .IMREAD_GRAYSCALE ).astype (np .float32 )
        n =(img -cv2 .GaussianBlur (img ,(3 ,3 ),0 )).std ();return n ,n >t 
    except :return 0 ,True 

def check_exposure (p ,lo =15 ,hi =240 ):
    try :
        mb =cv2 .imread (str (p ),cv2 .IMREAD_GRAYSCALE ).mean ()
        bad =mb <lo or mb >hi 
        return round (mb ,1 ),bad ,("Too dark"if mb <lo else "Overexposed"if mb >hi else "OK")
    except :return 0 ,True ,"Error"

def check_resolution (p ,mn =100_000 ):
    try :img =Image .open (p );w ,h =img .size ;return (w ,h ),(w *h )<mn 
    except :return (0 ,0 ),True 

def quality_score (p ):
    blur ,_ =check_blur (p ,99999 );noise ,_ =check_noise (p ,99999 )
    bright ,_ ,_ =check_exposure (p );(w ,h ),_ =check_resolution (p )
    return (min (100 ,blur /10 )*0.4 +max (0 ,100 -noise *5 )*0.2 +
    (100 -abs (bright -128 )/128 *100 )*0.2 +min (100 ,w *h /20000 )*0.2 )

def file_hash (p ):
    h =hashlib .md5 ()
    with open (p ,"rb")as f :
        for chunk in iter (lambda :f .read (8192 ),b""):h .update (chunk )
    return h .hexdigest ()

def perceptual_hash (p ):
    try :return imagehash .phash (Image .open (p ))
    except :return None 

def human_size (nb ):
    for u in ["B","KB","MB","GB"]:
        if nb <1024 :return f"{nb :.1f} {u }"
        nb /=1024 
    return f"{nb :.1f} TB"

def folder_size (folder ):
    return sum (f .stat ().st_size for f in Path (folder ).rglob ("*")if f .is_file ())

def fmt_time (s ):
    s =int (s );return f"{s }s"if s <60 else f"{s //60 }m {s %60 }s"

def label (parent ,text ,size =9 ,bold =False ,color =ON_SURF ,bg =SURF_LOWEST ):
    return tk .Label (parent ,text =text ,bg =bg ,fg =color ,
    font =(FONT ,size ,"bold"if bold else "normal"))

def divider (parent ,bg =BG ):
    tk .Frame (parent ,bg =OUTLINE_VAR ,height =1 ).pack (fill ="x",padx =0 ,pady =0 )

def card (parent ,padx =0 ,pady =(0 ,16 ),bg =SURF_LOWEST ):
    """White lifted card with ghost border."""
    outer =tk .Frame (parent ,bg =OUTLINE_VAR )
    outer .pack (fill ="x",padx =padx ,pady =pady )
    inner =tk .Frame (outer ,bg =bg )
    inner .pack (fill ="x",padx =1 ,pady =1 )
    return inner 

def section_label (parent ,text ,bg =BG ):
    f =tk .Frame (parent ,bg =bg )
    f .pack (fill ="x",padx =24 ,pady =(20 ,8 ))
    tk .Label (f ,text =text .upper (),bg =bg ,fg =OUTLINE ,
    font =(FONT ,8 ,"bold")).pack (side ="left")

def badge (parent ,text ,style ="ok",bg =SURF_LOWEST ):
    cfg =BADGE_OK if style =="ok"else BADGE_ERR if style =="err"else BADGE_WARN 
    tk .Label (parent ,text =text ,bg =cfg ["bg"],fg =cfg ["fg"],
    font =(FONT ,8 ,"bold"),padx =6 ,pady =2 ,
    relief ="flat").pack (side ="left",padx =(0 ,6 ))

def flat_btn (parent ,text ,cmd ,primary =True ):
    bg =PRIMARY if primary else SURF_HIGH 
    fg ="#FFFFFF"if primary else ON_SURF 
    b =tk .Button (parent ,text =text ,command =cmd ,
    bg =bg ,fg =fg ,font =(FONT ,9 ,"bold"),
    relief ="flat",padx =14 ,pady =7 ,
    cursor ="hand2",borderwidth =0 ,
    activebackground =PRIMARY_CTR if primary else SURF_HIGEST ,
    activeforeground =fg )
    b .pack (side ="left",padx =(0 ,8 ))
    return b 

def slim_progress (parent ,bg =BG ):
    """4px forensic slim progress bar."""
    track =tk .Frame (parent ,bg =SURF_HIGEST ,height =4 )
    track .pack (fill ="x",padx =24 ,pady =(0 ,4 ))
    bar =tk .Frame (track ,bg =PRIMARY ,height =4 ,width =0 )
    bar .place (x =0 ,y =0 ,relheight =1 )
    return bar ,track 

def mono_log (parent ,height =14 ):
    t =scrolledtext .ScrolledText (
    parent ,height =height ,bg =SURF_HIGH ,fg =ON_SURF_VAR ,
    font =(MONO ,8 ),relief ="flat",wrap ="word",
    insertbackground =ON_SURF ,borderwidth =0 ,
    selectbackground =PRIMARY_FXD ,selectforeground =ON_SURF )
    return t 

def text_input (parent ,var ,width =42 ):
    e =tk .Entry (parent ,textvariable =var ,width =width ,
    bg =SURF_LOW ,fg =ON_SURF ,relief ="flat",
    font =(FONT ,9 ),insertbackground =ON_SURF ,
    highlightthickness =1 ,
    highlightbackground =OUTLINE_VAR ,
    highlightcolor =PRIMARY )
    e .pack (side ="left",ipady =5 ,padx =(0 ,8 ))
    return e 

class App (AppBase ):

    def __init__ (self ):
        super ().__init__ ()
        self .title ("Inspector Pro — Forensic Digital Lab")
        self .geometry ("1100x760")
        self .minsize (900 ,600 )
        self .configure (bg =BG )
        init_db ()

        self ._current_heatmap =None 
        self ._active_tab =0 
        self ._stop_flag =threading .Event ()

        self ._build_sidebar ()
        self ._build_main_area ()

        if DND_AVAILABLE :
            self .drop_target_register (DND_FILES )
            self .dnd_bind ("<<Drop>>",self ._on_drop )

    def _build_sidebar (self ):
        sb =tk .Frame (self ,bg =SURF_LOW ,width =224 )
        sb .pack (side ="left",fill ="y")
        sb .pack_propagate (False )

        logo =tk .Frame (sb ,bg =SURF_LOW )
        logo .pack (fill ="x",padx =22 ,pady =(28 ,20 ))
        tk .Label (logo ,text ="Inspector Pro",bg =SURF_LOW ,fg =ON_SURF ,
        font =(FONT ,13 ,"bold")).pack (anchor ="w")
        tk .Label (logo ,text ="FORENSIC DIGITAL LAB",bg =SURF_LOW ,
        fg =OUTLINE ,font =(FONT ,7 ,"bold")).pack (anchor ="w")

        nav =tk .Frame (sb ,bg =SURF_LOW )
        nav .pack (fill ="x")

        self ._nav_btns =[]
        tabs =[
        ("🏠","Home",0 ),
        ("🔍","Tampering Detector",1 ),
        ("📁","Folder Sorter",2 ),
        ("🗄","History",3 ),
        ]
        for icon ,name ,idx in tabs :
            self ._nav_btns .append (
            self ._nav_item (nav ,icon ,name ,idx ))

        bot =tk .Frame (sb ,bg =SURF_LOW )
        bot .pack (side ="bottom",fill ="x",padx =0 ,pady =16 )
        for icon ,name in [("⚙","Settings"),("?","Help")]:
            f =tk .Frame (bot ,bg =SURF_LOW ,cursor ="hand2")
            f .pack (fill ="x")
            tk .Label (f ,text =f" {icon }  {name }",bg =SURF_LOW ,fg =OUTLINE ,
            font =(FONT ,9 ),padx =22 ,pady =8 ,anchor ="w"
            ).pack (fill ="x")

    def _nav_item (self ,parent ,icon ,name ,idx ):
        f =tk .Frame (parent ,bg =SURF_LOW ,cursor ="hand2")
        f .pack (fill ="x")
        lbl =tk .Label (f ,text =f"  {icon }  {name }",bg =SURF_LOW ,
        fg =ON_SURF_VAR ,font =(FONT ,9 ),padx =18 ,pady =10 ,
        anchor ="w")
        lbl .pack (fill ="x")
        pill =tk .Frame (f ,bg =SURF_LOW ,width =4 )
        pill .place (x =0 ,y =0 ,relheight =1 ,width =4 )

        def click (i =idx ,fr =f ,lb =lbl ,pl =pill ):
            self ._switch_tab (i )
        for w in (f ,lbl ):
            w .bind ("<Button-1>",lambda e ,fn =click :fn ())
            w .bind ("<Enter>",lambda e ,lb =lbl ,fr =f :(
            lb .config (bg =SURF if lb .cget ("fg")==ON_SURF_VAR else SURF_LOW ),
            fr .config (bg =SURF if lb .cget ("fg")==ON_SURF_VAR else SURF_LOW )))
            w .bind ("<Leave>",lambda e ,lb =lbl ,fr =f ,i =idx :(
            lb .config (bg =SURF_LOW if self ._active_tab !=i else SURF_LOWEST ),
            fr .config (bg =SURF_LOW if self ._active_tab !=i else SURF_LOWEST )))
        return (f ,lbl ,pill )

    def _switch_tab (self ,idx ):
        self ._active_tab =idx 

        for i ,(fr ,lb ,pl )in enumerate (self ._nav_btns ):
            if i ==idx :
                fr .config (bg =SURF_LOWEST );lb .config (bg =SURF_LOWEST ,fg =PRIMARY ,
                font =(FONT ,9 ,"bold"))
                pl .config (bg =PRIMARY )
            else :
                fr .config (bg =SURF_LOW );lb .config (bg =SURF_LOW ,fg =ON_SURF_VAR ,
                font =(FONT ,9 ,"normal"))
                pl .config (bg =SURF_LOW )

        for i ,panel in enumerate (self ._panels ):
            if i ==idx :panel .pack (fill ="both",expand =True )
            else :panel .pack_forget ()

        if idx ==0 :self ._load_home_stats ()

    def _build_main_area (self ):
        self ._main =tk .Frame (self ,bg =BG )
        self ._main .pack (side ="left",fill ="both",expand =True )

        topbar =tk .Frame (self ._main ,bg =SURF_LOWEST ,height =56 )
        topbar .pack (fill ="x")
        topbar .pack_propagate (False )
        tk .Frame (topbar ,bg =OUTLINE_VAR ,height =1 ).pack (side ="bottom",fill ="x")
        tk .Label (topbar ,text ="Image Inspector",bg =SURF_LOWEST ,fg =ON_SURF ,
        font =(FONT ,13 ,"bold")).pack (side ="left",padx =24 ,pady =16 )

        self ._stop_btn =tk .Button (
        topbar ,text ="⏹  Stop",command =self ._stop_task ,
        bg =ERR_CTR ,fg =ERR ,font =(FONT ,9 ,"bold"),
        relief ="flat",padx =10 ,pady =5 ,cursor ="hand2",
        state ="disabled",borderwidth =0 )
        self ._stop_btn .pack (side ="right",padx =(0 ,16 ),pady =12 )

        sys_frame =tk .Frame (topbar ,bg =SURF_LOWEST )
        sys_frame .pack (side ="right",padx =(0 ,20 ),pady =0 )

        cpu_row =tk .Frame (sys_frame ,bg =SURF_LOWEST )
        cpu_row .pack (anchor ="e",pady =(10 ,1 ))
        tk .Label (cpu_row ,text ="CPU",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,7 ,"bold"),width =4 ,anchor ="w").pack (side ="left")
        self ._cpu_track =tk .Frame (cpu_row ,bg =SURF_HIGH ,width =80 ,height =4 )
        self ._cpu_track .pack (side ="left",padx =(2 ,4 ))
        self ._cpu_track .pack_propagate (False )
        self ._cpu_bar =tk .Frame (self ._cpu_track ,bg =PRIMARY ,height =4 )
        self ._cpu_bar .place (x =0 ,y =0 ,relheight =1 ,width =0 )
        self ._cpu_lbl =tk .Label (cpu_row ,text ="0%",bg =SURF_LOWEST ,
        fg =ON_SURF_VAR ,font =(MONO ,7 ),width =4 )
        self ._cpu_lbl .pack (side ="left")

        ram_row =tk .Frame (sys_frame ,bg =SURF_LOWEST )
        ram_row .pack (anchor ="e",pady =(1 ,10 ))
        tk .Label (ram_row ,text ="RAM",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,7 ,"bold"),width =4 ,anchor ="w").pack (side ="left")
        self ._ram_track =tk .Frame (ram_row ,bg =SURF_HIGH ,width =80 ,height =4 )
        self ._ram_track .pack (side ="left",padx =(2 ,4 ))
        self ._ram_track .pack_propagate (False )
        self ._ram_bar =tk .Frame (self ._ram_track ,bg =PRIMARY_CTR ,height =4 )
        self ._ram_bar .place (x =0 ,y =0 ,relheight =1 ,width =0 )
        self ._ram_lbl =tk .Label (ram_row ,text ="0%",bg =SURF_LOWEST ,
        fg =ON_SURF_VAR ,font =(MONO ,7 ),width =4 )
        self ._ram_lbl .pack (side ="left")

        self ._update_sys_stats ()

        content =tk .Frame (self ._main ,bg =BG )
        content .pack (fill ="both",expand =True )

        self ._panels =[]
        for builder in [self ._build_home ,self ._build_tampering ,
        self ._build_sorter ,self ._build_history ]:
            p =tk .Frame (content ,bg =BG )
            self ._panels .append (p )
            builder (p )

        self ._switch_tab (0 )

    def _update_sys_stats (self ):
        """Poll CPU and RAM every second and update the top bar widgets."""
        try :
            cpu =psutil .cpu_percent (interval =None )
            ram =psutil .virtual_memory ().percent 
            cpu_color =ERR if cpu >85 else PRIMARY_CTR if cpu >60 else PRIMARY 
            ram_color =ERR if ram >85 else PRIMARY_CTR if ram >60 else PRIMARY_CTR 
            self ._cpu_bar .config (bg =cpu_color )
            self ._ram_bar .config (bg =ram_color )
            self ._cpu_bar .place (x =0 ,y =0 ,relheight =1 ,
            width =int (80 *cpu /100 ))
            self ._ram_bar .place (x =0 ,y =0 ,relheight =1 ,
            width =int (80 *ram /100 ))
            self ._cpu_lbl .config (text =f"{int (cpu )}%")
            self ._ram_lbl .config (text =f"{int (ram )}%")
        except Exception :
            pass 
        self .after (1000 ,self ._update_sys_stats )

    def _stop_task (self ):
        """Signal any running background thread to stop immediately."""
        self ._stop_flag .set ()
        self ._stop_btn .config (state ="disabled",text ="Stopping…",
        bg ="#FFDAD6",fg ="#93000A")

        self .after (2000 ,lambda :self ._stop_btn .config (
        text ="⏹  Stop",bg =ERR_CTR ,fg =ERR ))

    def _task_start (self ):
        """Called at the start of every analysis/sort task."""
        self ._stop_flag .clear ()
        self ._stop_btn .config (state ="normal",text ="⏹  Stop")

    def _task_done (self ):
        """Called when a task finishes (normally or via stop)."""
        self .after (0 ,lambda :self ._stop_btn .config (
        state ="disabled",text ="⏹  Stop"))

    def _on_drop (self ,event ):
        path =event .data .strip ().strip ("{}")
        if os .path .isfile (path ):
            self .t1_path .set (path );self ._switch_tab (1 )
            self .t1_mode .set ("single");self ._toggle_mode ()
        elif os .path .isdir (path ):
            self .t1_batch_path .set (path );self ._switch_tab (1 )
            self .t1_mode .set ("batch");self ._toggle_mode ()

    def _build_home (self ,p ):
        canvas =tk .Canvas (p ,bg =BG ,highlightthickness =0 )
        sb =ttk .Scrollbar (p ,orient ="vertical",command =canvas .yview )
        canvas .configure (yscrollcommand =sb .set )
        sb .pack (side ="right",fill ="y")
        canvas .pack (fill ="both",expand =True )
        inner =tk .Frame (canvas ,bg =BG )
        win =canvas .create_window ((0 ,0 ),window =inner ,anchor ="nw")
        canvas .bind ("<Configure>",lambda e :canvas .itemconfig (win ,width =e .width ))
        inner .bind ("<Configure>",lambda e :canvas .configure (
        scrollregion =canvas .bbox ("all")))

        hero =tk .Frame (inner ,bg =PRIMARY )
        hero .pack (fill ="x")
        tk .Label (hero ,text ="Forensic Digital Lab",bg =PRIMARY ,fg ="#FFFFFF",
        font =(FONT ,22 ,"bold")).pack (anchor ="w",padx =40 ,pady =(36 ,4 ))
        tk .Label (hero ,text ="Detect image tampering · Sort by quality · Preserve history",
        bg =PRIMARY ,fg ="#A5C8FF",
        font =(FONT ,10 )).pack (anchor ="w",padx =40 ,pady =(0 ,36 ))

        section_label (inner ,"Overview")
        sr =tk .Frame (inner ,bg =BG )
        sr .pack (fill ="x",padx =24 ,pady =(0 ,8 ))
        self ._stat_vars ={}
        for key ,icon ,label_txt ,color in [
        ("total","🖼","Total Scanned",PRIMARY ),
        ("tamper","🔴","Tampered Found",ERR ),
        ("clean","✅","Clean / Good","#388E3C"),
        ("sorted","📁","Sorted Files","#E64A19"),
        ]:
            c =tk .Frame (sr ,bg =SURF_LOWEST ,
            highlightthickness =1 ,highlightbackground =OUTLINE_VAR )
            c .pack (side ="left",expand =True ,fill ="x",padx =(0 ,12 ),pady =4 )
            tk .Label (c ,text =icon ,bg =SURF_LOWEST ,font =(FONT ,20 )
            ).pack (pady =(16 ,2 ))
            var =tk .StringVar (value ="—")
            self ._stat_vars [key ]=var 
            tk .Label (c ,textvariable =var ,bg =SURF_LOWEST ,fg =color ,
            font =(FONT ,20 ,"bold")).pack ()
            tk .Label (c ,text =label_txt ,bg =SURF_LOWEST ,fg =OUTLINE ,
            font =(FONT ,8 )).pack (pady =(2 ,16 ))

        section_label (inner ,"Quick Actions")
        for title ,desc ,color ,tab in [
        ("Analyse Single Image",
        "Check any image for tampering, edits or forgery",
        PRIMARY ,1 ),
        ("Batch Scan a Folder",
        "Scan every image in a folder and get a full report",
        PRIMARY_CTR ,1 ),
        ("Sort Image Folder",
        "Automatically split images into Good and Bad folders",
        "#388E3C",2 ),
        ("View History",
        "Browse all past analyses and sort results",
        "#E64A19",3 ),
        ]:
            ac =tk .Frame (inner ,bg =SURF_LOWEST ,
            highlightthickness =1 ,highlightbackground =OUTLINE_VAR ,
            cursor ="hand2")
            ac .pack (fill ="x",padx =24 ,pady =(0 ,8 ))
            accent =tk .Frame (ac ,bg =color ,width =5 )
            accent .pack (side ="left",fill ="y")
            body =tk .Frame (ac ,bg =SURF_LOWEST )
            body .pack (side ="left",fill ="both",expand =True ,padx =18 ,pady =14 )
            tk .Label (body ,text =title ,bg =SURF_LOWEST ,fg =ON_SURF ,
            font =(FONT ,11 ,"bold"),anchor ="w").pack (fill ="x")
            tk .Label (body ,text =desc ,bg =SURF_LOWEST ,fg =ON_SURF_VAR ,
            font =(FONT ,8 ),anchor ="w").pack (fill ="x")
            arrow =tk .Label (ac ,text ="›",bg =SURF_LOWEST ,fg =OUTLINE ,
            font =(FONT ,18 ))
            arrow .pack (side ="right",padx =18 )
            for w in (ac ,accent ,body ,arrow ):
                w .bind ("<Button-1>",lambda e ,t =tab :self ._switch_tab (t ))
                w .bind ("<Enter>",lambda e ,a =ac ,bd =body :(
                a .config (highlightbackground =PRIMARY ),
                bd .config (bg =PRIMARY_FXD ),a .config (bg =PRIMARY_FXD )))
                w .bind ("<Leave>",lambda e ,a =ac ,bd =body :(
                a .config (highlightbackground =OUTLINE_VAR ),
                bd .config (bg =SURF_LOWEST ),a .config (bg =SURF_LOWEST )))

        section_label (inner ,"Recent Activity")
        self ._home_recent =tk .Frame (inner ,bg =BG )
        self ._home_recent .pack (fill ="x",padx =24 ,pady =(0 ,32 ))
        self ._load_recent_home ()

    def _load_home_stats (self ):
        try :
            rows =fetch_history ()
            total =len (rows )
            tamper =sum (1 for r in rows if "TAMPERED"in (r [5 ]or ""))
            clean =sum (1 for r in rows if "AUTHENTIC"in (r [5 ]or "")or r [5 ]=="GOOD")
            sorted_ =sum (1 for r in rows if r [4 ]=="sort")
            self ._stat_vars ["total"].set (str (total ))
            self ._stat_vars ["tamper"].set (str (tamper ))
            self ._stat_vars ["clean"].set (str (clean ))
            self ._stat_vars ["sorted"].set (str (sorted_ ))
        except :pass 

    def _load_recent_home (self ):
        for w in self ._home_recent .winfo_children ():w .destroy ()
        rows =fetch_history ()[:5 ]
        if not rows :
            tk .Label (self ._home_recent ,
            text ="No activity yet. Analyse an image or sort a folder to begin.",
            bg =BG ,fg =OUTLINE ,font =(FONT ,9 )).pack (anchor ="w",pady =10 )
            return 
        for row in rows :
            verdict =row [5 ]or ""
            color =("#388E3C"if "AUTHENTIC"in verdict or verdict =="GOOD"else 
            ERR if "TAMPERED"in verdict or "BAD"in verdict else 
            "#E64A19")
            icon =("✅"if color =="#388E3C"else 
            "🔴"if color ==ERR else "🟡")
            rf =tk .Frame (self ._home_recent ,bg =SURF_LOWEST ,
            highlightthickness =1 ,highlightbackground =OUTLINE_VAR )
            rf .pack (fill ="x",pady =3 )
            tk .Label (rf ,text =icon ,bg =SURF_LOWEST ,
            font =(FONT ,10 )).pack (side ="left",padx =10 ,pady =8 )
            tk .Label (rf ,text =row [1 ],bg =SURF_LOWEST ,fg =ON_SURF ,
            font =(FONT ,9 ,"bold"),anchor ="w",width =34 
            ).pack (side ="left")
            tk .Label (rf ,text =verdict ,bg =SURF_LOWEST ,fg =color ,
            font =(FONT ,8 )).pack (side ="left",padx =10 )
            tk .Label (rf ,text =row [3 ],bg =SURF_LOWEST ,fg =OUTLINE ,
            font =(FONT ,8 )).pack (side ="right",padx =12 )

    def _build_tampering (self ,p ):

        hdr =tk .Frame (p ,bg =BG )
        hdr .pack (fill ="x",padx =32 ,pady =(28 ,20 ))
        hl =tk .Frame (hdr ,bg =PRIMARY_FXD ,width =36 ,height =36 )
        hl .pack (side ="left",padx =(0 ,12 ))
        hl .pack_propagate (False )
        tk .Label (hl ,text ="🔍",bg =PRIMARY_FXD ,font =(FONT ,14 )
        ).place (relx =.5 ,rely =.5 ,anchor ="center")
        tk .Label (hdr ,text ="Tampering Detector",bg =BG ,fg =ON_SURF ,
        font =(FONT ,18 ,"bold")).pack (anchor ="w")
        tk .Label (hdr ,text ="ELA, metadata, noise pattern and copy-move analysis for any image.",
        bg =BG ,fg =ON_SURF_VAR ,font =(FONT ,9 )).pack (anchor ="w")

        cols =tk .Frame (p ,bg =BG )
        cols .pack (fill ="both",expand =True ,padx =24 )

        left =tk .Frame (cols ,bg =BG ,width =320 )
        right =tk .Frame (cols ,bg =BG )
        left .pack (side ="left",fill ="y",padx =(0 ,16 ))
        left .pack_propagate (False )
        right .pack (side ="left",fill ="both",expand =True )

        mc =card (left ,pady =(0 ,12 ))
        tk .Label (mc ,text ="SELECT INPUT METHOD",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,8 ,"bold")).pack (anchor ="w",padx =16 ,pady =(14 ,10 ))

        modes =tk .Frame (mc ,bg =SURF_LOWEST )
        modes .pack (fill ="x",padx =16 ,pady =(0 ,14 ))
        self .t1_mode =tk .StringVar (value ="single")

        self ._mode_single =tk .Frame (modes ,bg =PRIMARY_FXD ,cursor ="hand2",
        highlightthickness =2 ,
        highlightbackground =PRIMARY )
        self ._mode_single .pack (side ="left",expand =True ,fill ="x",padx =(0 ,6 ))
        tk .Label (self ._mode_single ,text ="🖼\nSingle Image",
        bg =PRIMARY_FXD ,fg =PRIMARY ,
        font =(FONT ,8 ,"bold"),pady =12 ).pack (expand =True )
        self ._mode_single .bind ("<Button-1>",lambda e :(
        self .t1_mode .set ("single"),self ._toggle_mode ()))

        self ._mode_batch =tk .Frame (modes ,bg =SURF_LOW ,cursor ="hand2",
        highlightthickness =1 ,
        highlightbackground =OUTLINE_VAR )
        self ._mode_batch .pack (side ="left",expand =True ,fill ="x")
        tk .Label (self ._mode_batch ,text ="📦\nBatch Folder",
        bg =SURF_LOW ,fg =ON_SURF_VAR ,
        font =(FONT ,8 ,"bold"),pady =12 ).pack (expand =True )
        self ._mode_batch .bind ("<Button-1>",lambda e :(
        self .t1_mode .set ("batch"),self ._toggle_mode ()))

        dz =tk .Frame (mc ,bg =SURF_LOW ,cursor ="hand2",
        highlightthickness =1 ,highlightbackground =OUTLINE_VAR )
        dz .pack (fill ="x",padx =16 ,pady =(0 ,14 ))
        tk .Label (dz ,text ="⬆\n\nDrag & drop image files here\nJPG, PNG, TIFF — any size",
        bg =SURF_LOW ,fg =ON_SURF_VAR ,font =(FONT ,8 ),pady =20 
        ).pack (expand =True )

        self ._single_frame =tk .Frame (mc ,bg =SURF_LOWEST )
        self .t1_path =tk .StringVar ()
        rf =tk .Frame (self ._single_frame ,bg =SURF_LOWEST )
        rf .pack (fill ="x",padx =16 ,pady =(0 ,4 ))
        tk .Label (rf ,text ="Image file",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,8 ),width =10 ,anchor ="w").pack (side ="left")
        text_input (rf ,self .t1_path ,18 )
        tk .Button (rf ,text ="Browse",command =self ._browse_single ,
        bg =SEC_CTR ,fg =ON_SURF ,font =(FONT ,8 ,"bold"),
        relief ="flat",padx =8 ,pady =4 ,cursor ="hand2"
        ).pack (side ="left")

        self ._batch_frame =tk .Frame (mc ,bg =SURF_LOWEST )
        self .t1_batch_path =tk .StringVar ()
        rf2 =tk .Frame (self ._batch_frame ,bg =SURF_LOWEST )
        rf2 .pack (fill ="x",padx =16 ,pady =(0 ,4 ))
        tk .Label (rf2 ,text ="Folder",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,8 ),width =10 ,anchor ="w").pack (side ="left")
        text_input (rf2 ,self .t1_batch_path ,18 )
        tk .Button (rf2 ,text ="Browse",command =self ._browse_batch ,
        bg =SEC_CTR ,fg =ON_SURF ,font =(FONT ,8 ,"bold"),
        relief ="flat",padx =8 ,pady =4 ,cursor ="hand2"
        ).pack (side ="left")

        ac =card (left ,pady =(0 ,12 ))
        bf =tk .Frame (ac ,bg =SURF_LOWEST )
        bf .pack (fill ="x",padx =16 ,pady =14 )
        self ._run_btn =tk .Button (bf ,text ="  ▶  Start Analysis",
        command =self ._run_t1 ,
        bg =PRIMARY ,fg ="#FFFFFF",
        font =(FONT ,10 ,"bold"),relief ="flat",
        padx =14 ,pady =9 ,cursor ="hand2",
        width =24 ,anchor ="center")
        self ._run_btn .pack (fill ="x",pady =(0 ,8 ))
        self .heatmap_btn =tk .Button (bf ,text ="  🌡  View Heatmap",
        command =self ._open_heatmap ,
        bg =SURF_HIGH ,fg =ON_SURF ,
        font =(FONT ,9 ,"bold"),relief ="flat",
        padx =14 ,pady =7 ,cursor ="hand2",
        width =24 ,state ="disabled")
        self .heatmap_btn .pack (fill ="x")

        self ._toggle_mode ()

        pc =card (right ,pady =(0 ,12 ))
        ph =tk .Frame (pc ,bg =SURF_LOWEST )
        ph .pack (fill ="x",padx =20 ,pady =(14 ,6 ))
        self .t1_proc_lbl =tk .StringVar (value ="Ready to scan")
        tk .Label (ph ,textvariable =self .t1_proc_lbl ,bg =SURF_LOWEST ,fg =ON_SURF_VAR ,
        font =(FONT ,8 ,"bold")).pack (side ="left")
        self .t1_timer_lbl =tk .StringVar (value ="")
        tk .Label (ph ,textvariable =self .t1_timer_lbl ,bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(MONO ,8 )).pack (side ="right")

        self ._t1_bar ,self ._t1_track =slim_progress (pc )
        tk .Frame (pc ,bg =BG ,height =8 ).pack ()

        log_c =card (right ,pady =(0 ,0 ))
        log_hdr =tk .Frame (log_c ,bg =SURF_HIGH )
        log_hdr .pack (fill ="x")
        tk .Label (log_hdr ,text ="FORENSIC LOG OUTPUT",bg =SURF_HIGH ,fg =OUTLINE ,
        font =(FONT ,8 ,"bold"),padx =16 ,pady =8 ).pack (side ="left")
        tk .Button (log_hdr ,text ="Clear",bg =SURF_HIGH ,fg =OUTLINE ,
        font =(FONT ,8 ),relief ="flat",cursor ="hand2",
        command =lambda :self .t1_log .delete ("1.0","end")
        ).pack (side ="right",padx =12 )
        self .t1_log =mono_log (log_c ,height =20 )
        self .t1_log .pack (fill ="both",expand =True ,padx =0 ,pady =0 )

    def _toggle_mode (self ):
        is_single =self .t1_mode .get ()=="single"

        self ._mode_single .config (
        bg =PRIMARY_FXD if is_single else SURF_LOW ,
        highlightbackground =PRIMARY if is_single else OUTLINE_VAR ,
        highlightthickness =2 if is_single else 1 )
        self ._mode_single .winfo_children ()[0 ].config (
        bg =PRIMARY_FXD if is_single else SURF_LOW ,
        fg =PRIMARY if is_single else ON_SURF_VAR )
        self ._mode_batch .config (
        bg =PRIMARY_FXD if not is_single else SURF_LOW ,
        highlightbackground =PRIMARY if not is_single else OUTLINE_VAR ,
        highlightthickness =2 if not is_single else 1 )
        self ._mode_batch .winfo_children ()[0 ].config (
        bg =PRIMARY_FXD if not is_single else SURF_LOW ,
        fg =PRIMARY if not is_single else ON_SURF_VAR )

        if is_single :
            self ._single_frame .pack (fill ="x",pady =(0 ,14 ))
            self ._batch_frame .pack_forget ()
        else :
            self ._batch_frame .pack (fill ="x",pady =(0 ,14 ))
            self ._single_frame .pack_forget ()

    def _browse_single (self ):
        p =filedialog .askopenfilename (
        title ="Select image",
        filetypes =[("Images","*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),("All","*.*")])
        if p :self .t1_path .set (p )

    def _browse_batch (self ):
        p =filedialog .askdirectory (title ="Select folder of images")
        if p :self .t1_batch_path .set (p )

    def _run_t1 (self ):
        self ._task_start ()
        self .t1_log .delete ("1.0","end")
        self .heatmap_btn .config (state ="disabled")
        self ._current_heatmap =None 
        self ._set_t1_bar (0 )
        self .t1_timer_lbl .set ("")

        if self .t1_mode .get ()=="single":
            path =self .t1_path .get ().strip ()
            if not path or not os .path .isfile (path ):
                messagebox .showerror ("Error","Please select a valid image.");return 
            self .t1_proc_lbl .set ("Initialising scan…")
            self ._t1_log (f"[{datetime .now ().strftime ('%H:%M:%S')}] INITIALIZING_SCAN: {os .path .basename (path )}\n")
            threading .Thread (target =self ._do_single ,args =(path ,),daemon =True ).start ()
        else :
            folder =self .t1_batch_path .get ().strip ()
            if not folder or not os .path .isdir (folder ):
                messagebox .showerror ("Error","Please select a valid folder.");return 
            self .t1_proc_lbl .set ("Starting batch scan…")
            threading .Thread (target =self ._do_batch ,args =(folder ,),daemon =True ).start ()

    def _do_single (self ,path ):
        t0 =time .time ()
        self ._t1_log (f"[{datetime .now ().strftime ('%H:%M:%S')}] EXTRACTING_METADATA: Parsing EXIF headers…\n")
        self .after (0 ,lambda :self ._set_t1_bar (15 ))
        try :
            r =analyse_tampering (path ,stop_flag =self ._stop_flag )
        except InterruptedError :
            self ._t1_log ("\n[STOPPED] Analysis cancelled by user.\n")
            self ._task_done ();return 
        except Exception as e :
            self ._t1_log (f"ERROR: {e }\n");self ._task_done ();return 
        elapsed =time .time ()-t0 

        self .after (0 ,lambda :self ._set_t1_bar (100 ))
        self .after (0 ,lambda :self .t1_proc_lbl .set (f"Scan complete — {r ['verdict']}"))
        self .after (0 ,lambda :self .t1_timer_lbl .set (f"Done in {fmt_time (elapsed )}"))

        v =r ["verdict"]
        icon =("✅"if "AUTHENTIC"in v else "🟡"if "POSSIBLY"in v else "🔴")
        lines =[
        f"[{datetime .now ().strftime ('%H:%M:%S')}] SCAN_COMPLETE: {os .path .basename (path )}\n",
        f"{'─'*56 }\n",
        f"  {icon }  VERDICT        : {v }\n",
        f"      Overall score  : {r ['overall']:.1f} / 100\n",
        f"      Analysis time  : {fmt_time (elapsed )}\n\n",
        f"── ① ELA (Error Level Analysis) ────────────────\n",
        f"   Score   : {r ['ela']['score']} / 100\n",
        f"   Mean Δ  : {r ['ela']['mean']}    Std: {r ['ela']['std']}\n",
        f"   Reading : {'Low — authentic'if r ['ela']['score']<20 else 'Moderate — uneven compression'if r ['ela']['score']<45 else 'HIGH — SUSPICIOUS REGIONS FOUND'}\n\n",
        f"── ② Metadata / EXIF ───────────────────────────\n",
        ]
        for k ,v2 in r ["metadata"]["info"].items ():
            lines .append (f"   {k :<22}: {v2 }\n")
        for flag in r ["metadata"]["flags"]:
            lines .append (f"   WARNING: {flag }\n")
        if not r ["metadata"]["flags"]:
            lines .append ("   ✓ No suspicious metadata flags\n")
        lines +=[
        f"\n── ③ Noise Consistency ─────────────────────────\n",
        f"   Score   : {r ['noise']['score']} / 100\n",
        f"   Reading : {r ['noise']['desc']}\n\n",
        f"── ④ Copy-Move Detection ───────────────────────\n",
        f"   Score   : {r ['copy_move']['score']} / 100\n",
        f"   Reading : {r ['copy_move']['desc']}\n",
        f"{'─'*56 }\n",
        f"Click  🌡 View Heatmap  to see suspicious regions.\n",
        ]
        for line in lines :self ._t1_log (line )

        if r ["ela"]["image"]:
            try :
                orig =Image .open (path ).convert ("RGB")
                heat =make_ela_heatmap (r ["ela"]["image"],orig )
                self ._current_heatmap =(orig ,heat )
                self .after (0 ,lambda :self .heatmap_btn .config (state ="normal"))
            except :pass 

        save_to_db ([{
        "filename":os .path .basename (path ),"filepath":path ,"mode":"single",
        "verdict":r ["verdict"],"ela_score":r ["ela"]["score"],
        "noise_score":r ["noise"]["score"],"cm_score":r ["copy_move"]["score"],
        "overall":r ["overall"]
        }])
        self ._task_done ()
        self .after (0 ,self ._refresh_history )

    def _do_batch (self ,folder ):
        exts ={".jpg",".jpeg",".png",".bmp",".tiff",".webp"}
        files =[f for f in Path (folder ).iterdir ()
        if f .suffix .lower ()in exts and f .is_file ()]
        if not files :
            self ._t1_log ("No image files found.\n");return 

        total =len (files )
        counts ={};times =[];db_rec =[]
        self ._t1_log (f"[{datetime .now ().strftime ('%H:%M:%S')}] BATCH_START: {total } images found\n{'─'*56 }\n")

        for i ,fpath in enumerate (files ):
            t0 =time .time ()
            self .after (0 ,lambda v =i :self ._set_t1_bar (v /total *100 ))
            if times :
                avg =sum (times )/len (times );rem =avg *(total -i )
                self .after (0 ,lambda r =rem ,e =sum (times ):self .t1_timer_lbl .set (
                f"Remaining: {fmt_time (r )}  Elapsed: {fmt_time (e )}"))
            self .after (0 ,lambda n =fpath .name ,j =i +1 :self .t1_proc_lbl .set (
            f"Scanning {j }/{total }: {n }"))

            try :
                r =analyse_tampering (fpath ,stop_flag =self ._stop_flag )
            except InterruptedError :
                self ._t1_log (f"\n[STOPPED] Batch cancelled after {i } of {total } images.\n")
                self ._task_done ()
                save_to_db (db_rec )
                self .after (0 ,self ._refresh_history )
                return 
            except Exception as e :
                self ._t1_log (f"ERROR {fpath .name }: {e }\n");continue 

            elapsed =time .time ()-t0 ;times .append (elapsed )
            v =r ["verdict"];counts [v ]=counts .get (v ,0 )+1 
            icon =("✅"if "AUTHENTIC"in v else "🟡"if "POSSIBLY"in v else "🔴")
            self ._t1_log (
            f"[{datetime .now ().strftime ('%H:%M:%S')}] {icon } {fpath .name :<36} "
            f"{r ['overall']:5.1f}/100  {v }\n")
            db_rec .append ({"filename":fpath .name ,"filepath":str (fpath ),"mode":"batch",
            "verdict":v ,"ela_score":r ["ela"]["score"],
            "noise_score":r ["noise"]["score"],"cm_score":r ["copy_move"]["score"],
            "overall":r ["overall"]})

        total_t =sum (times )
        self .after (0 ,lambda :self ._set_t1_bar (100 ))
        self .after (0 ,lambda :self .t1_proc_lbl .set ("Batch scan complete"))
        self .after (0 ,lambda :self .t1_timer_lbl .set (f"Done in {fmt_time (total_t )}"))
        self ._t1_log (
        f"{'─'*56 }\n"
        f"BATCH_SUMMARY — {total } images\n"
        f"  ✅ Likely Authentic : {counts .get ('LIKELY AUTHENTIC',0 )}\n"
        f"  🟡 Possibly Edited  : {counts .get ('POSSIBLY EDITED',0 )}\n"
        f"  🔴 Likely Tampered  : {counts .get ('LIKELY TAMPERED',0 )}\n"
        f"  Total time         : {fmt_time (total_t )}\n"
        f"  Avg per image      : {fmt_time (total_t /total if total else 0 )}\n")
        self ._task_done ()
        save_to_db (db_rec )
        self .after (0 ,self ._refresh_history )

    def _set_t1_bar (self ,pct ):
        try :
            w =self ._t1_track .winfo_width ()
            self ._t1_bar .place (x =0 ,y =0 ,height =4 ,width =int (w *pct /100 ))
        except :pass 

    def _t1_log (self ,text ):
        self .after (0 ,lambda :(self .t1_log .insert ("end",text ),self .t1_log .see ("end")))

    def _open_heatmap (self ):
        if self ._current_heatmap :
            HeatmapViewer (self ,*self ._current_heatmap )

    def _build_sorter (self ,p ):

        hdr =tk .Frame (p ,bg =BG )
        hdr .pack (fill ="x",padx =32 ,pady =(28 ,20 ))
        hl =tk .Frame (hdr ,bg ="#E8F5E9",width =36 ,height =36 )
        hl .pack (side ="left",padx =(0 ,12 ));hl .pack_propagate (False )
        tk .Label (hl ,text ="📁",bg ="#E8F5E9",
        font =(FONT ,14 )).place (relx =.5 ,rely =.5 ,anchor ="center")
        tk .Label (hdr ,text ="Folder Sorter",bg =BG ,fg =ON_SURF ,
        font =(FONT ,18 ,"bold")).pack (anchor ="w")
        tk .Label (hdr ,text ="Automatically separate images into Good and Bad based on quality criteria.",
        bg =BG ,fg =ON_SURF_VAR ,font =(FONT ,9 )).pack (anchor ="w")

        canvas =tk .Canvas (p ,bg =BG ,highlightthickness =0 )
        sb2 =ttk .Scrollbar (p ,orient ="vertical",command =canvas .yview )
        canvas .configure (yscrollcommand =sb2 .set )
        sb2 .pack (side ="right",fill ="y")
        canvas .pack (fill ="both",expand =True )
        inner =tk .Frame (canvas ,bg =BG )
        win =canvas .create_window ((0 ,0 ),window =inner ,anchor ="nw")
        canvas .bind ("<Configure>",lambda e :canvas .itemconfig (win ,width =e .width ))
        inner .bind ("<Configure>",lambda e :canvas .configure (scrollregion =canvas .bbox ("all")))

        section_label (inner ,"Directory Configuration")
        dc =card (inner ,padx =24 ,pady =(0 ,12 ))
        self .t2_src =tk .StringVar ()
        self .t2_good =tk .StringVar ()
        self .t2_bad =tk .StringVar ()
        for lbl ,var ,cmd ,clr in [
        ("Source folder",self .t2_src ,lambda :self ._pick (self .t2_src ),OUTLINE ),
        ("Destination — GOOD",self .t2_good ,lambda :self ._pick (self .t2_good ),"#388E3C"),
        ("Destination — BAD",self .t2_bad ,lambda :self ._pick (self .t2_bad ),ERR ),
        ]:
            rw =tk .Frame (dc ,bg =SURF_LOWEST )
            rw .pack (fill ="x",padx =0 ,pady =4 )
            tk .Label (rw ,text =lbl ,bg =SURF_LOWEST ,fg =OUTLINE ,
            font =(FONT ,8 ,"bold"),width =22 ,anchor ="w").pack (side ="left")
            text_input (rw ,var ,34 )
            tk .Button (rw ,text ="Browse",command =cmd ,
            bg =SURF_HIGH ,fg =ON_SURF ,font =(FONT ,8 ),
            relief ="flat",padx =8 ,pady =4 ,cursor ="hand2",
            activebackground =SURF_HIGEST 
            ).pack (side ="left")

        section_label (inner ,"Quality Criteria")
        qc =card (inner ,padx =24 ,pady =(0 ,12 ))
        tk .Label (qc ,text ="Mark as BAD if any of these are true:",
        bg =SURF_LOWEST ,fg =ON_SURF_VAR ,font =(FONT ,8 )
        ).pack (anchor ="w",padx =0 ,pady =(4 ,10 ))

        self .opt_blur =tk .BooleanVar (value =True )
        self .opt_noise =tk .BooleanVar (value =True )
        self .opt_expo =tk .BooleanVar (value =True )
        self .opt_res =tk .BooleanVar (value =True )
        self .opt_dup =tk .BooleanVar (value =True )
        self .opt_tamp =tk .BooleanVar (value =False )

        cg =tk .Frame (qc ,bg =SURF_LOWEST )
        cg .pack (fill ="x")
        checks =[
        (self .opt_blur ,"Blurry","Low sharpness / out of focus"),
        (self .opt_noise ,"High Noise","Excessive digital grain or artifacts"),
        (self .opt_expo ,"Bad Exposure","Too dark or overexposed"),
        (self .opt_res ,"Low Resolution","Under 100,000 total pixels"),
        (self .opt_dup ,"Duplicates (keep best)","Exact or near-identical copies"),
        (self .opt_tamp ,"Tampering Suspected","Copy-move score over 40"),
        ]
        for i ,(var ,title ,desc )in enumerate (checks ):
            col =i %2 ;row =i //2 
            f =tk .Frame (cg ,bg =SURF_LOWEST )
            f .grid (row =row ,column =col ,sticky ="ew",padx =(0 ,16 ),pady =6 )
            cg .columnconfigure (col ,weight =1 )
            inner_f =tk .Frame (f ,bg =SURF_LOWEST )
            inner_f .pack (anchor ="w")
            tk .Checkbutton (inner_f ,variable =var ,bg =SURF_LOWEST ,
            selectcolor =SURF_LOW ,activebackground =SURF_LOWEST ,
            cursor ="hand2").pack (side ="left")
            tx =tk .Frame (inner_f ,bg =SURF_LOWEST )
            tx .pack (side ="left")
            tk .Label (tx ,text =title ,bg =SURF_LOWEST ,fg =ON_SURF ,
            font =(FONT ,9 ,"bold"),anchor ="w").pack (anchor ="w")
            tk .Label (tx ,text =desc ,bg =SURF_LOWEST ,fg =OUTLINE ,
            font =(FONT ,7 ),anchor ="w").pack (anchor ="w")

        section_label (inner ,"Action")
        ac2 =card (inner ,padx =24 ,pady =(0 ,12 ))
        mf =tk .Frame (ac2 ,bg =SURF_LOWEST )
        mf .pack (fill ="x",pady =(4 ,10 ))
        tk .Label (mf ,text ="File action:",bg =SURF_LOWEST ,fg =OUTLINE ,
        font =(FONT ,8 ),width =12 ,anchor ="w").pack (side ="left")
        self .t2_mode =tk .StringVar (value ="copy")
        for val ,lbl in [("copy","Copy files (safe)"),("move","Move files")]:
            tk .Radiobutton (mf ,text =lbl ,variable =self .t2_mode ,value =val ,
            bg =SURF_LOWEST ,fg =ON_SURF ,selectcolor =SURF_LOW ,
            activebackground =SURF_LOWEST ,
            font =(FONT ,9 )).pack (side ="left",padx =10 )

        run2 =tk .Button (ac2 ,text ="  ▶  Start Sorting",command =self ._run_t2 ,
        bg =PRIMARY ,fg ="#FFFFFF",font =(FONT ,10 ,"bold"),
        relief ="flat",padx =14 ,pady =9 ,cursor ="hand2")
        run2 .pack (fill ="x",pady =(0 ,4 ))

        section_label (inner ,"Progress")
        pg =card (inner ,padx =24 ,pady =(0 ,12 ))
        ph2 =tk .Frame (pg ,bg =SURF_LOWEST )
        ph2 .pack (fill ="x",pady =(8 ,4 ))
        self .t2_status =tk .StringVar (value ="Ready.")
        tk .Label (ph2 ,textvariable =self .t2_status ,bg =SURF_LOWEST ,
        fg =ON_SURF_VAR ,font =(FONT ,8 ,"bold")).pack (side ="left")
        self .t2_timer_lbl =tk .StringVar (value ="")
        tk .Label (ph2 ,textvariable =self .t2_timer_lbl ,bg =SURF_LOWEST ,
        fg =OUTLINE ,font =(MONO ,8 )).pack (side ="right")
        self ._t2_bar ,self ._t2_track =slim_progress (pg )

        section_label (inner ,"File Log")
        lc2 =card (inner ,padx =24 ,pady =(0 ,12 ))
        lhdr =tk .Frame (lc2 ,bg =SURF_HIGH )
        lhdr .pack (fill ="x")
        tk .Label (lhdr ,text ="SORT LOG",bg =SURF_HIGH ,fg =OUTLINE ,
        font =(FONT ,8 ,"bold"),padx =16 ,pady =8 ).pack (side ="left")
        self .t2_log =mono_log (lc2 ,height =8 )
        self .t2_log .pack (fill ="x")

        self .t2_stats_frame =tk .Frame (inner ,bg =SURF_LOWEST ,
        highlightthickness =1 ,
        highlightbackground =OUTLINE_VAR )
        self .t2_stats_var =tk .StringVar ()
        tk .Label (self .t2_stats_frame ,textvariable =self .t2_stats_var ,
        bg =SURF_LOWEST ,fg =ON_SURF_VAR ,font =(MONO ,8 ),
        justify ="left").pack (anchor ="w",padx =16 ,pady =12 )

    def _pick (self ,var ):
        p =filedialog .askdirectory (title ="Select folder")
        if p :var .set (p )

    def _run_t2 (self ):
        self ._task_start ()
        src ,good ,bad =(self .t2_src .get ().strip (),
        self .t2_good .get ().strip (),
        self .t2_bad .get ().strip ())
        if not os .path .isdir (src ):
            messagebox .showerror ("Error","Please select a valid source folder.");return 
        if not good or not bad :
            messagebox .showerror ("Error","Please set both output folders.");return 
        os .makedirs (good ,exist_ok =True );os .makedirs (bad ,exist_ok =True )
        opts ={k :v .get ()for k ,v in [
        ("blur",self .opt_blur ),("noise",self .opt_noise ),("expo",self .opt_expo ),
        ("res",self .opt_res ),("dup",self .opt_dup ),("tamp",self .opt_tamp )]}
        self .t2_log .delete ("1.0","end")
        self .t2_stats_frame .pack_forget ()
        self ._set_t2_bar (0 );self .t2_timer_lbl .set ("")
        threading .Thread (target =self ._do_t2 ,
        args =(src ,good ,bad ,opts ,self .t2_mode .get ()),
        daemon =True ).start ()

    def _do_t2 (self ,src ,good_dir ,bad_dir ,opts ,mode ):
        exts ={".jpg",".jpeg",".png",".bmp",".tiff",".webp"}
        files =[f for f in Path (src ).iterdir ()
        if f .suffix .lower ()in exts and f .is_file ()]
        if not files :
            self ._t2_log ("No image files found.\n");return 

        total =len (files )
        self .after (0 ,lambda :self .t2_status .set (f"Processing {total } images…"))

        dup_bad ={}
        if opts ["dup"]:
            exact =defaultdict (list )
            for f in files :exact [file_hash (f )].append (f )
            unique =[]
            for grp in exact .values ():
                if len (grp )>1 :
                    scored =sorted (grp ,key =quality_score ,reverse =True )
                    for other in scored [1 :]:dup_bad [other ]=scored [0 ].name 
                    unique .append (scored [0 ])
                else :unique .append (grp [0 ])
            seen_ph ,ph_groups ={},[]
            for fpath in unique :
                ph =perceptual_hash (fpath )
                if ph is None :continue 
                matched =False 
                for prev_ph ,gi in seen_ph .items ():
                    if abs (ph -prev_ph )<=8 :
                        ph_groups [gi ].append (fpath );matched =True ;break 
                if not matched :
                    seen_ph [ph ]=len (ph_groups );ph_groups .append ([fpath ])
            for grp in ph_groups :
                if len (grp )>1 :
                    scored =sorted (grp ,key =quality_score ,reverse =True )
                    for other in scored [1 :]:dup_bad [other ]=scored [0 ].name 

        counters ={"good":0 ,"bad":0 }
        rcounts ={"Blurry":0 ,"Noisy":0 ,"Exposure":0 ,"Low-res":0 ,"Duplicate":0 ,"Tampered":0 }
        times =[];db_rec =[]

        for i ,fpath in enumerate (files ):
            t0 =time .time ()
            self .after (0 ,lambda v =i :self ._set_t2_bar (v /total *100 ))
            if times :
                avg =sum (times )/len (times );rem =avg *(total -i )
                self .after (0 ,lambda r =rem ,e =sum (times ):self .t2_timer_lbl .set (
                f"Remaining: {fmt_time (r )}  Elapsed: {fmt_time (e )}"))

            if self ._stop_flag .is_set ():
                self ._t2_log (f"\n[STOPPED] Sort cancelled after {i } of {total } files.\n"
                f"  Good so far: {counters ['good']}  Bad so far: {counters ['bad']}\n")
                self ._task_done ()
                save_to_db (db_rec )
                self .after (0 ,self ._refresh_history )
                return 
            reasons =[]
            if opts ["dup"]and fpath in dup_bad :
                reasons .append (f"Duplicate — best kept: {dup_bad [fpath ]}")
                rcounts ["Duplicate"]+=1 
            if not reasons :
                if opts ["blur"]:
                    s ,bad =check_blur (fpath )
                    if bad :reasons .append (f"Blurry ({s :.1f})");rcounts ["Blurry"]+=1 
                if opts ["noise"]:
                    s ,bad =check_noise (fpath )
                    if bad :reasons .append (f"Noisy ({s :.1f})");rcounts ["Noisy"]+=1 
                if opts ["expo"]:
                    b ,bad ,rsn =check_exposure (fpath )
                    if bad :reasons .append (f"{rsn } ({b })");rcounts ["Exposure"]+=1 
                if opts ["res"]:
                    (w ,h ),bad =check_resolution (fpath )
                    if bad :reasons .append (f"Low-res ({w }×{h })");rcounts ["Low-res"]+=1 
                if opts ["tamp"]:
                    cs ,_ =copy_move_detection (fpath )
                    if cs >40 :reasons .append (f"Tampering ({cs })");rcounts ["Tampered"]+=1 

            dest_dir =bad_dir if reasons else good_dir 
            dest =os .path .join (dest_dir ,fpath .name )
            if os .path .exists (dest ):
                dest =os .path .join (dest_dir ,f"{fpath .stem }_{i }{fpath .suffix }")
            try :
                (shutil .move if mode =="move"else shutil .copy2 )(str (fpath ),dest )
                if reasons :
                    counters ["bad"]+=1 
                    self ._t2_log (f"❌  {fpath .name }  →  BAD   | {', '.join (reasons )}\n")
                else :
                    counters ["good"]+=1 
                    self ._t2_log (f"✅  {fpath .name }  →  GOOD\n")
            except Exception as e :
                self ._t2_log (f"⚠   {fpath .name }: {e }\n")
            times .append (time .time ()-t0 )
            db_rec .append ({"filename":fpath .name ,"filepath":str (fpath ),"mode":"sort",
            "verdict":("BAD: "+reasons [0 ])if reasons else "GOOD",
            "destination":dest_dir })

        total_t =sum (times )
        good_sz =folder_size (good_dir );bad_sz =folder_size (bad_dir )
        gp =int (counters ["good"]/total *100 )if total else 0 
        bp =int (counters ["bad"]/total *100 )if total else 0 
        BAR =28 
        stats =(
        f"{'═'*52 }\n  SORT COMPLETE\n{'─'*52 }\n"
        f"  Total scanned      : {total } files\n"
        f"  ✅ Good             : {counters ['good']} ({gp }%)\n"
        f"  ❌ Bad              : {counters ['bad']} ({bp }%)\n\n"
        f"  Good  [{'█'*int (BAR *gp /100 ):<{BAR }}]  {gp }%\n"
        f"  Bad   [{'█'*int (BAR *bp /100 ):<{BAR }}]  {bp }%\n\n"
        f"  📂 Good folder size : {human_size (good_sz )}\n"
        f"  📂 Bad folder size  : {human_size (bad_sz )}\n"
        f"  💾 Recoverable space: {human_size (bad_sz )}\n\n"
        f"  Breakdown:\n"
        )
        for rsn ,cnt in rcounts .items ():
            if cnt :stats +=f"    {rsn :<16}: {cnt }\n"
        stats +=(f"\n  ⏱  Total time      : {fmt_time (total_t )}\n"
        f"  ⚡ Avg per image   : {fmt_time (total_t /total if total else 0 )}\n"
        f"{'═'*52 }")

        self .after (0 ,lambda s =stats :(
        self .t2_stats_var .set (s ),
        self .t2_stats_frame .pack (fill ="x",padx =24 ,pady =(0 ,24 ))))
        self .after (0 ,lambda :self ._set_t2_bar (100 ))
        self .after (0 ,lambda :self .t2_status .set (
        f"Done! Good: {counters ['good']}  Bad: {counters ['bad']}"))
        messagebox .showinfo ("Sort Complete",
        f"✅ Good : {counters ['good']}\n❌ Bad  : {counters ['bad']}\n"
        f"⏱ Time : {fmt_time (total_t )}")
        self ._task_done ()
        save_to_db (db_rec )
        self .after (0 ,self ._refresh_history )

    def _set_t2_bar (self ,pct ):
        try :
            w =self ._t2_track .winfo_width ()
            self ._t2_bar .place (x =0 ,y =0 ,height =4 ,width =int (w *pct /100 ))
        except :pass 

    def _t2_log (self ,text ):
        self .after (0 ,lambda :(self .t2_log .insert ("end",text ),self .t2_log .see ("end")))

    def _build_history (self ,p ):

        hdr =tk .Frame (p ,bg =BG )
        hdr .pack (fill ="x",padx =32 ,pady =(28 ,0 ))
        tk .Label (hdr ,text ="Analysis History",bg =BG ,fg =ON_SURF ,
        font =(FONT ,18 ,"bold")).pack (side ="left",anchor ="w")

        bar =tk .Frame (p ,bg =BG )
        bar .pack (fill ="x",padx =32 ,pady =(12 ,16 ))
        self .t3_search =tk .StringVar ()
        se =tk .Entry (bar ,textvariable =self .t3_search ,width =32 ,
        bg =SURF_LOW ,fg =ON_SURF ,relief ="flat",
        font =(FONT ,9 ),insertbackground =ON_SURF ,
        highlightthickness =1 ,
        highlightbackground =OUTLINE_VAR ,
        highlightcolor =PRIMARY )
        se .pack (side ="left",ipady =6 ,padx =(0 ,8 ))
        tk .Button (bar ,text ="Search",command =self ._refresh_history ,
        bg =PRIMARY ,fg ="#FFFFFF",font =(FONT ,9 ,"bold"),
        relief ="flat",padx =12 ,pady =6 ,cursor ="hand2"
        ).pack (side ="left",padx =(0 ,6 ))
        tk .Button (bar ,text ="Refresh",command =self ._refresh_history ,
        bg =SURF_HIGH ,fg =ON_SURF ,font =(FONT ,9 ),
        relief ="flat",padx =10 ,pady =6 ,cursor ="hand2"
        ).pack (side ="left",padx =(0 ,6 ))
        tk .Button (bar ,text ="Clear All",command =self ._clear_history ,
        bg =ERR_CTR ,fg =ERR ,font =(FONT ,9 ),
        relief ="flat",padx =10 ,pady =6 ,cursor ="hand2"
        ).pack (side ="right")

        cols =("File","Date & Time","Mode","Verdict","Score","Destination")
        style =ttk .Style ()
        style .configure ("FG.Treeview",
        background =SURF_LOWEST ,foreground =ON_SURF ,
        fieldbackground =SURF_LOWEST ,
        rowheight =26 ,font =(FONT ,9 ))
        style .configure ("FG.Treeview.Heading",
        background =SURF_LOW ,foreground =ON_SURF_VAR ,
        font =(FONT ,8 ,"bold"))
        style .map ("FG.Treeview",
        background =[("selected",PRIMARY_FXD )],
        foreground =[("selected",ON_SURF )])

        self .t3_tree =ttk .Treeview (p ,columns =cols ,show ="headings",
        height =22 ,style ="FG.Treeview")
        for col ,w in zip (cols ,[210 ,140 ,65 ,175 ,55 ,160 ]):
            self .t3_tree .heading (col ,text =col )
            self .t3_tree .column (col ,width =w ,anchor ="w")

        sb3 =ttk .Scrollbar (p ,orient ="vertical",command =self .t3_tree .yview )
        self .t3_tree .configure (yscrollcommand =sb3 .set )
        self .t3_tree .pack (side ="left",fill ="both",expand =True ,
        padx =(32 ,0 ),pady =(0 ,16 ))
        sb3 .pack (side ="left",fill ="y",pady =(0 ,16 ),padx =(0 ,16 ))

        self ._refresh_history ()

    def _refresh_history (self ):
        search =self .t3_search .get ().strip ()if hasattr (self ,"t3_search")else ""
        rows =fetch_history (search )
        self .after (0 ,lambda :self ._populate_tree (rows ))
        self .after (0 ,self ._load_home_stats )
        self .after (0 ,self ._load_recent_home )

    def _populate_tree (self ,rows ):
        self .t3_tree .delete (*self .t3_tree .get_children ())
        for row in rows :
            verdict =row [5 ]or "";score =f"{row [9 ]:.1f}"if row [9 ]else "—"
            tag =("bad"if any (x in verdict for x in ["TAMPERED","BAD"])else 
            "good"if any (x in verdict for x in ["AUTHENTIC","GOOD"])else 
            "mid"if "POSSIBLY"in verdict else "")
            self .t3_tree .insert ("","end",
            values =(row [1 ],row [3 ],row [4 ],verdict ,score ,row [10 ]or "—"),
            tags =(tag ,))
        self .t3_tree .tag_configure ("bad",foreground =ERR )
        self .t3_tree .tag_configure ("good",foreground ="#388E3C")
        self .t3_tree .tag_configure ("mid",foreground ="#E64A19")

    def _clear_history (self ):
        if messagebox .askyesno ("Clear History","Delete all history records?"):
            clear_history ();self ._refresh_history ()

class HeatmapViewer (tk .Toplevel ):
    W ,H =380 ,300 

    def __init__ (self ,parent ,original ,heatmap ):
        super ().__init__ (parent )
        self .title ("ELA Heatmap Viewer")
        self .configure (bg =SURF_LOWEST )
        self .resizable (False ,False )
        self .orig =original .resize ((self .W ,self .H ),Image .LANCZOS )
        self .heat =heatmap .resize ((self .W ,self .H ),Image .LANCZOS )

        bar =tk .Frame (self ,bg =PRIMARY ,height =44 )
        bar .pack (fill ="x");bar .pack_propagate (False )
        tk .Label (bar ,text ="  🌡  ELA Heatmap — Suspicious Region Viewer",
        bg =PRIMARY ,fg ="#FFFFFF",
        font =(FONT ,10 ,"bold")).pack (side ="left",padx =10 ,pady =10 )

        hdr =tk .Frame (self ,bg =SURF_LOWEST )
        hdr .pack (fill ="x",pady =(12 ,4 ))
        for txt ,col in [("Original","#388E3C"),
        ("Blend Preview",ON_SURF_VAR ),
        ("ELA Heatmap",ERR )]:
            tk .Label (hdr ,text =txt ,bg =SURF_LOWEST ,fg =col ,
            font =(FONT ,10 ,"bold"),width =20 ,anchor ="center"
            ).pack (side ="left",padx =8 )

        cf =tk .Frame (self ,bg =SURF_LOWEST )
        cf .pack (padx =10 )
        self .c_orig =tk .Canvas (cf ,width =self .W ,height =self .H ,
        bg =SURF_LOW ,highlightthickness =1 ,
        highlightbackground ="#388E3C")
        self .c_blend =tk .Canvas (cf ,width =self .W ,height =self .H ,
        bg =SURF_LOW ,highlightthickness =1 ,
        highlightbackground =OUTLINE_VAR )
        self .c_heat =tk .Canvas (cf ,width =self .W ,height =self .H ,
        bg =SURF_LOW ,highlightthickness =1 ,
        highlightbackground =ERR )
        for c in (self .c_orig ,self .c_blend ,self .c_heat ):
            c .pack (side ="left",padx =5 )

        sf =tk .Frame (self ,bg =SURF_LOWEST )
        sf .pack (fill ="x",padx =18 ,pady =(10 ,4 ))
        tk .Label (sf ,text ="← Original",bg =SURF_LOWEST ,
        fg ="#388E3C",font =(FONT ,8 )).pack (side ="left")
        tk .Label (sf ,text ="Heatmap →",bg =SURF_LOWEST ,
        fg =ERR ,font =(FONT ,8 )).pack (side ="right")

        self .blend_var =tk .DoubleVar (value =50 )
        ttk .Scale (self ,from_ =0 ,to =100 ,variable =self .blend_var ,
        orient ="horizontal",length =self .W *3 +32 ,
        command =self ._slide ).pack (padx =18 ,pady =(0 ,6 ))

        leg =tk .Frame (self ,bg =SURF_LOWEST )
        leg .pack (pady =(2 ,16 ))
        tk .Label (leg ,text ="🟢  Green = Clean",
        bg =SURF_LOWEST ,fg ="#388E3C",
        font =(FONT ,9 )).pack (side ="left",padx =18 )
        tk .Label (leg ,text ="🔴  Red = Suspicious / possibly edited",
        bg =SURF_LOWEST ,fg =ERR ,
        font =(FONT ,9 )).pack (side ="left",padx =18 )

        self ._tk_orig =self ._tk_blend =self ._tk_heat =None 
        self ._draw ();self ._slide (50 )

    def _draw (self ):
        self ._tk_orig =ImageTk .PhotoImage (self .orig )
        self .c_orig .create_image (0 ,0 ,anchor ="nw",image =self ._tk_orig )
        self ._tk_heat =ImageTk .PhotoImage (self .heat )
        self .c_heat .create_image (0 ,0 ,anchor ="nw",image =self ._tk_heat )

    def _slide (self ,val ):
        alpha =float (val )/100 
        blended =Image .blend (self .orig ,self .heat ,alpha =alpha )
        self ._tk_blend =ImageTk .PhotoImage (blended )
        self .c_blend .delete ("all")
        self .c_blend .create_image (0 ,0 ,anchor ="nw",image =self ._tk_blend )
        self .c_blend .create_text (self .W //2 ,self .H -12 ,
        text =f"{int (float (val ))}% heatmap",
        fill =PRIMARY_CTR ,font =(FONT ,8 ,"bold"))

if __name__ =="__main__":
    app =App ()
    app .mainloop ()
