"""
TagHandler.py
Shared tag-picker dialog for Piwigo-connected applications.

Public API
----------
    show_tag_picker(root, tags_var, cache)
        Open a modal checklist dialog that fetches tags from Piwigo and lets
        the user select one or more.  The cache list is populated on the first
        call so subsequent opens skip the network round-trip.
"""

import threading
import tkinter as tk
from tkinter import ttk

import AlbumHierarchy


def _center_dialog(root: tk.Tk, dlg: tk.Toplevel):
    root.update_idletasks()
    dlg.update_idletasks()
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    rw, rh = root.winfo_width(), root.winfo_height()
    dw, dh = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry(f"+{rx + (rw - dw) // 2}+{ry + (rh - dh) // 2}")


def show_tag_picker(root: tk.Tk, tags_var: "tk.StringVar", cache: list):
    """Modal checklist dialog for selecting Piwigo tags.

    Parameters
    ----------
    root      : parent Tk window (used for centering)
    tags_var  : StringVar holding the current comma-separated tag string
    cache     : single-element list [None | list[dict]]; populated on first call
                so subsequent opens skip the network round-trip
    """
    current_tags = {t.strip() for t in tags_var.get().split(',') if t.strip()}

    dlg = tk.Toplevel(root)
    dlg.title("Select Tags")
    dlg.grab_set()

    # ── Filter bar ──────────────────────────────────────────────────────────
    filter_frame = ttk.Frame(dlg, padding=(8, 8, 8, 4))
    filter_frame.pack(fill='x')
    ttk.Label(filter_frame, text="Filter:").pack(side='left', padx=(0, 4))
    filter_var = tk.StringVar()
    ttk.Entry(filter_frame, textvariable=filter_var).pack(side='left', fill='x', expand=True)

    # ── Scrollable checklist ─────────────────────────────────────────────────
    list_outer = ttk.Frame(dlg, padding=(8, 0, 8, 0))
    list_outer.pack(fill='both', expand=True)
    canvas = tk.Canvas(list_outer, highlightthickness=0)
    vsb = ttk.Scrollbar(list_outer, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    inner = ttk.Frame(canvas)
    win_id = canvas.create_window((0, 0), window=inner, anchor='nw')
    inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))

    def _mwheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
    canvas.bind_all('<MouseWheel>', _mwheel)

    # ── Status line ──────────────────────────────────────────────────────────
    status_var = tk.StringVar(value="Loading tags from Piwigo…")
    ttk.Label(dlg, textvariable=status_var, foreground='gray',
              padding=(8, 2, 8, 2)).pack(fill='x')

    # ── Add new tag ──────────────────────────────────────────────────────────
    add_frame = ttk.Frame(dlg, padding=(8, 4, 8, 4))
    add_frame.pack(fill='x')
    ttk.Label(add_frame, text="New tag:").pack(side='left', padx=(0, 4))
    new_tag_var = tk.StringVar()
    new_tag_entry = ttk.Entry(add_frame, textvariable=new_tag_var)
    new_tag_entry.pack(side='left', fill='x', expand=True, padx=(0, 4))

    check_vars:    dict[str, tk.BooleanVar] = {}
    check_buttons: dict[str, ttk.Checkbutton] = {}
    all_tag_rows:  list[tuple[str, str]] = []

    def _add_row(name: str, count: int, checked: bool):
        var = tk.BooleanVar(value=checked)
        check_vars[name] = var
        label = f"{name}  ({count:,})" if count else name
        btn = ttk.Checkbutton(inner, text=label, variable=var)
        btn.pack(fill='x', padx=4, pady=1)
        check_buttons[name] = btn
        all_tag_rows.append((name.lower(), name))

    def _add_new_tag():
        name = new_tag_var.get().strip()
        if not name:
            return
        if name not in check_vars:
            _add_row(name, 0, checked=True)
            inner.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.yview_moveto(1.0)
        else:
            check_vars[name].set(True)
        new_tag_var.set('')

    ttk.Button(add_frame, text="Add", command=_add_new_tag).pack(side='left')
    new_tag_entry.bind('<Return>', lambda e: _add_new_tag())

    def _populate(tags: list[dict]):
        for tag in sorted(tags, key=lambda t: t['name'].lower()):
            name = tag['name']
            _add_row(name, tag.get('counter', 0), checked=name in current_tags)
        for name in sorted(current_tags):
            if name not in check_vars:
                _add_row(name, 0, checked=True)
        status_var.set(f"{len(tags)} tag{'s' if len(tags) != 1 else ''} on site")
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox('all'))

    def _on_filter(*_):
        q = filter_var.get().strip().lower()
        for name_lower, name in all_tag_rows:
            if q in name_lower:
                check_buttons[name].pack(fill='x', padx=4, pady=1)
            else:
                check_buttons[name].pack_forget()

    filter_var.trace_add('write', _on_filter)

    def _fetch():
        if cache[0] is not None:
            root.after(0, lambda: _populate(cache[0]))
            return
        try:
            params = AlbumHierarchy.load_params()
            client = AlbumHierarchy.PiwigoClient(
                params['url'], params['username'], params['password'],
                verify_ssl=params.get('verify_ssl', True))
            client.login(params['username'], params['password'])
            tags = client.get_tags()
            client.logout()
            cache[0] = tags
            root.after(0, lambda: _populate(tags))
        except Exception as e:
            root.after(0, lambda e=e: status_var.set(f"Error loading tags: {e}"))

    threading.Thread(target=_fetch, daemon=True).start()

    # ── Bottom buttons ────────────────────────────────────────────────────────
    btn_frame = ttk.Frame(dlg, padding=(8, 4, 8, 10))
    btn_frame.pack(fill='x')

    def _clear_all():
        for var in check_vars.values():
            var.set(False)

    ttk.Button(btn_frame, text="Clear All", command=_clear_all).pack(side='left')

    def _ok():
        selected = sorted(name for name, var in check_vars.items() if var.get())
        tags_var.set(', '.join(selected))
        canvas.unbind_all('<MouseWheel>')
        dlg.destroy()

    def _cancel():
        canvas.unbind_all('<MouseWheel>')
        dlg.destroy()

    ttk.Button(btn_frame, text="Cancel", command=_cancel).pack(side='right', padx=(4, 0))
    ttk.Button(btn_frame, text="OK", command=_ok).pack(side='right')
    dlg.bind('<Return>', lambda e: _ok())
    dlg.protocol('WM_DELETE_WINDOW', _cancel)

    dlg.geometry("400x520")
    _center_dialog(root, dlg)