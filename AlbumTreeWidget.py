"""
AlbumTreeWidget.py
Reusable tkinter album-hierarchy tree widget for Piwigo applications.

Provides a Filter bar, scrollable Treeview, and right-click context menu
(Add sub-album / Rename / Delete).  All Piwigo API calls are made on
background threads; the caller is notified via callbacks.

Public API
----------
    AlbumTreeWidget(parent, root, on_select, on_mutation,
                    set_status=None, focus_filter=False)

    Attributes
        .frame                  ttk.Frame — pack/grid this into the caller's layout
        .tree                   the underlying ttk.Treeview
        .tree_all_items         list of (iid, name_lower, fullname)
        .tree_fullname_by_iid   dict  iid → fullname

    Methods
        .populate(hierarchy, select_id=None)
            Fill or refresh the tree from a hierarchy list.
            select_id, if given, is pre-selected with its ancestor chain opened.
"""

import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import AlbumHierarchy


class AlbumTreeWidget:
    """Album hierarchy tree with filter, RMB add/rename/delete, and callbacks.

    Parameters
    ----------
    parent        tk.Widget   parent widget to build into
    root          tk.Tk       main window — for after() and dialog centering
    on_select     callable    (album_id: int, fullname: str) → None
                              fired on every <<TreeviewSelect>> / double-click
    on_mutation   callable    (action: str, album_id: int, fullname: str) → None
                              fired after add/rename/delete succeeds;
                              action is "add", "rename", or "delete"
    set_status    callable    (msg: str) → None  (optional, no-op if omitted)
    focus_filter  bool        focus the filter Entry immediately (default False)
    """

    def __init__(self, parent: tk.Widget, root: tk.Tk,
                 on_select, on_mutation,
                 set_status=None, focus_filter: bool = False,
                 select_delay_ms: int = 0,
                 on_selection_changing=None):
        self.root                    = root
        self._on_select              = on_select
        self._on_mut                 = on_mutation
        self._set_status             = set_status or (lambda msg: None)
        self._select_delay_ms        = select_delay_ms
        self._on_selection_changing  = on_selection_changing
        self._pending_select         = None   # after() id for debounced select
        self._last_fired_iid         = None   # iid of last on_select that actually fired
        # Optional drag-start callback: (album_id, fullname, x_root, y_root) -> None
        # Set externally after construction (e.g. by PhotosEditor).
        self._on_album_drag_start:  "callable | None" = None
        # Optional RMB-menu extension hook: (menu, album_id, node) -> None
        # Set externally after construction to append app-specific menu items.
        self._extend_rmb_menu:      "callable | None" = None
        self._atw_press_pos:        "tuple | None"    = None
        self._atw_press_iid:        "str | None"      = None

        self._hierarchy:         list = []
        self._node_by_iid:       dict = {}
        self._parent_iid_by_iid: dict = {}

        self.tree_all_items:       list = []
        self.tree_fullname_by_iid: dict = {}

        self.frame = ttk.Frame(parent)
        self._build(focus_filter)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build(self, focus_filter: bool):
        filter_frame = ttk.Frame(self.frame)
        filter_frame.pack(fill='x', pady=(0, 4))
        ttk.Label(filter_frame, text="Filter:").pack(side='left', padx=(0, 4))
        self._filter_var = tk.StringVar()
        fe = ttk.Entry(filter_frame, textvariable=self._filter_var)
        fe.pack(side='left', fill='x', expand=True)
        if focus_filter:
            fe.focus_set()

        tree_frame = ttk.Frame(self.frame)
        tree_frame.pack(fill='both', expand=True)
        yscroll = ttk.Scrollbar(tree_frame, orient='vertical')
        xscroll = ttk.Scrollbar(tree_frame, orient='horizontal')
        self.tree = ttk.Treeview(tree_frame, selectmode='browse', show='tree',
                                 yscrollcommand=yscroll.set,
                                 xscrollcommand=xscroll.set)
        yscroll.config(command=self.tree.yview)
        xscroll.config(command=self.tree.xview)
        yscroll.pack(side='right', fill='y')
        xscroll.pack(side='bottom', fill='x')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.column('#0', minwidth=200)

        self._filter_var.trace_add('write', self._on_filter)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Double-1>',         self._on_tree_select)
        self.tree.bind('<Button-3>',         self._show_rmb_menu)
        self.tree.bind('<MouseWheel>',
            lambda e: self.tree.yview_scroll(-1 * (e.delta // 120), 'units'))
        self.tree.bind('<ButtonPress-1>',   self._on_atw_press,   add=True)
        self.tree.bind('<B1-Motion>',       self._on_atw_motion,  add=True)
        self.tree.bind('<ButtonRelease-1>', self._on_atw_release,  add=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def populate(self, hierarchy: list, select_id: "int | None" = None):
        """Fill or refresh the tree from a hierarchy list."""
        self._hierarchy = hierarchy
        self._node_by_iid.clear()
        self._parent_iid_by_iid.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree_all_items = []
        self.tree_fullname_by_iid = {}

        self._insert_nodes('', hierarchy)

        sel_iid = str(select_id) if select_id is not None else None
        if sel_iid and self.tree.exists(sel_iid):
            self._open_ancestors(sel_iid)
            self.tree.selection_set(sel_iid)
            self.tree.see(sel_iid)
        else:
            for iid, _, _ in self.tree_all_items:
                if self._parent_iid_by_iid.get(iid) == '':
                    self.tree.item(iid, open=True)

    # ── Tree population helpers ───────────────────────────────────────────────

    def _insert_nodes(self, par_iid: str, nodes: list):
        for node in nodes:
            iid   = str(node['id'])
            count = node.get('total_nb_images', 0)
            text  = f"{node['name']}  ({count:,})"
            self.tree.insert(par_iid, 'end', iid=iid, text=text, open=False)
            fullname = node.get('fullname', node['name'])
            self.tree_all_items.append((iid, node['name'].lower(), fullname))
            self.tree_fullname_by_iid[iid] = fullname
            self._node_by_iid[iid]         = node
            self._parent_iid_by_iid[iid]   = par_iid
            if node.get('children'):
                self._insert_nodes(iid, node['children'])

    def _rebuild_full_tree(self, select_iid: "str | None" = None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree_all_items = []
        self.tree_fullname_by_iid = {}
        self._node_by_iid.clear()
        self._parent_iid_by_iid.clear()
        self._insert_nodes('', self._hierarchy)
        if select_iid and self.tree.exists(select_iid):
            self._open_ancestors(select_iid)
            self.tree.selection_set(select_iid)
            self.tree.see(select_iid)
        else:
            for iid, _, _ in self.tree_all_items:
                if self._parent_iid_by_iid.get(iid) == '':
                    self.tree.item(iid, open=True)

    def _open_ancestors(self, iid: str):
        anc = self._parent_iid_by_iid.get(iid, '')
        while anc:
            self.tree.item(anc, open=True)
            anc = self._parent_iid_by_iid.get(anc, '')

    # ── Filter ────────────────────────────────────────────────────────────────

    def _on_filter(self, *_):
        q = self._filter_var.get().strip().lower()
        if not q:
            sel = self.tree.selection()
            self._rebuild_full_tree(select_iid=sel[0] if sel else None)
            return

        matches = [(iid, fullname)
                   for iid, _nl, fullname in self.tree_all_items
                   if q in fullname.lower()]

        for item in self.tree.get_children():
            self.tree.delete(item)
        if not matches:
            return

        for iid, fullname in matches:
            self.tree.insert('', 'end', iid=iid, text=fullname, open=False)
        self.tree.selection_set(matches[0][0])
        self.tree.see(matches[0][0])

    # ── Tree selection ────────────────────────────────────────────────────────

    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if self._select_delay_ms > 0:
            if iid != self._last_fired_iid and self._on_selection_changing:
                self._on_selection_changing()
            if self._pending_select:
                self.root.after_cancel(self._pending_select)
            self._pending_select = self.root.after(
                self._select_delay_ms,
                lambda i=iid: self._fire_select(i))
        else:
            self._fire_select(iid)

    def _fire_select(self, iid: str):
        self._pending_select = None
        self._last_fired_iid = iid
        self._on_select(int(iid), self.tree_fullname_by_iid.get(iid, ''))

    # ── RMB menu ──────────────────────────────────────────────────────────────

    def _show_rmb_menu(self, event):
        iid  = self.tree.identify_row(event.y)
        if not iid:
            return
        node = self._node_by_iid.get(iid)
        if node is None:
            return
        short    = node['name']
        is_empty = node.get('total_nb_images', 1) == 0

        menu = tk.Menu(self.tree, tearoff=0)
        menu.add_command(
            label=f"Add sub-album under \"{short}\"",
            command=lambda: self.root.after(50, lambda: self._do_add_sub_album(iid)))
        menu.add_command(
            label=f"Rename \"{short}\"",
            command=lambda: self.root.after(50, lambda: self._do_rename(iid)))
        menu.add_separator()
        menu.add_command(
            label=f"Delete \"{short}\"",
            command=lambda: self.root.after(50, lambda: self._do_delete(iid)),
            state='normal' if is_empty else 'disabled')
        if self._extend_rmb_menu is not None:
            self._extend_rmb_menu(menu, int(iid), node)
        menu.tk_popup(event.x_root, event.y_root)

    # ── Add sub-album ─────────────────────────────────────────────────────────

    def _do_add_sub_album(self, par_iid: str):
        node     = self._node_by_iid[par_iid]
        par_name = node['name']
        par_full = self.tree_fullname_by_iid.get(par_iid, par_name)

        dlg = tk.Toplevel(self.root)
        dlg.title('Add Sub-Album')
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=f"New sub-album under \"{par_name}\":",
                  padding=(16, 12, 16, 4)).pack()
        name_var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=name_var, width=40)
        entry.pack(padx=16, pady=(0, 8))
        entry.focus_set()
        msg_var = tk.StringVar()
        ttk.Label(dlg, textvariable=msg_var, foreground='red',
                  padding=(16, 0, 16, 4)).pack()
        btn_row = ttk.Frame(dlg, padding=(16, 0, 16, 12))
        btn_row.pack()

        def _create():
            name = name_var.get().strip()
            if not name:
                msg_var.set('Please enter a name.')
                return
            ok_btn.config(state='disabled')
            cancel_btn.config(state='disabled')
            msg_var.set('Creating…')

            def worker():
                try:
                    c      = self._make_client()
                    new_id = c.create_album(name, parent_id=int(par_iid))
                    c.logout()
                    new_full = f"{par_full} / {name}"
                    new_node = {'id': new_id, 'name': name, 'fullname': new_full,
                                'nb_images': 0, 'total_nb_images': 0, 'children': []}
                    self.root.after(0, lambda: _add_done(new_node))
                except Exception as e:
                    self.root.after(0, lambda e=e: _add_err(str(e)))

            def _add_err(msg: str):
                msg_var.set(f"Error: {msg}")
                ok_btn.config(state='normal')
                cancel_btn.config(state='normal')

            threading.Thread(target=worker, daemon=True).start()

        def _add_done(new_node: dict):
            dlg.destroy()
            node['children'].append(new_node)
            node['children'].sort(key=lambda n: n['name'].lower())
            self._save_hierarchy()
            new_iid = str(new_node['id'])
            self._node_by_iid[new_iid]        = new_node
            self._parent_iid_by_iid[new_iid]  = par_iid
            self.tree_fullname_by_iid[new_iid] = new_node['fullname']
            self.tree_all_items.append(
                (new_iid, new_node['name'].lower(), new_node['fullname']))
            siblings   = self.tree.get_children(par_iid)
            insert_idx = 'end'
            for sib in siblings:
                sib_node = self._node_by_iid.get(sib)
                if sib_node and sib_node['name'].lower() > new_node['name'].lower():
                    insert_idx = self.tree.index(sib)
                    break
            self.tree.insert(par_iid, insert_idx, iid=new_iid,
                             text=f"{new_node['name']}  (0)", open=False)
            self.tree.see(new_iid)
            self.tree.selection_set(new_iid)
            self._set_status(f"Created sub-album \"{new_node['name']}\".")
            self._on_mut('add', new_node['id'], new_node['fullname'])

        ok_btn     = ttk.Button(btn_row, text='Create', command=_create)
        cancel_btn = ttk.Button(btn_row, text='Cancel', command=dlg.destroy)
        ok_btn.pack(side='left', padx=(0, 8))
        cancel_btn.pack(side='left')
        entry.bind('<Return>', lambda e: _create())
        entry.bind('<Escape>', lambda e: dlg.destroy())
        self._center_on_root(dlg)

    # ── Rename ────────────────────────────────────────────────────────────────

    def _do_rename(self, iid: str):
        node         = self._node_by_iid[iid]
        current_name = node['name']

        dlg = tk.Toplevel(self.root)
        dlg.title('Rename Album')
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Rename \"{current_name}\" to:",
                  padding=(16, 12, 16, 4)).pack()
        name_var = tk.StringVar(value=current_name)
        entry = ttk.Entry(dlg, textvariable=name_var, width=40)
        entry.pack(padx=16, pady=(0, 8))
        entry.select_range(0, 'end')
        entry.focus_set()
        msg_var = tk.StringVar()
        ttk.Label(dlg, textvariable=msg_var, foreground='red',
                  padding=(16, 0, 16, 4)).pack()
        btn_row = ttk.Frame(dlg, padding=(16, 0, 16, 12))
        btn_row.pack()

        def _rename():
            new_name = name_var.get().strip()
            if not new_name or new_name == current_name:
                dlg.destroy()
                return
            ok_btn.config(state='disabled')
            cancel_btn.config(state='disabled')
            msg_var.set('Renaming…')

            def worker():
                try:
                    c = self._make_client()
                    c.rename_album(int(iid), new_name)
                    c.logout()
                    self.root.after(0, lambda: _rename_done(new_name))
                except Exception as e:
                    self.root.after(0, lambda e=e: _rename_err(str(e)))

            def _rename_err(msg: str):
                msg_var.set(f"Error: {msg}")
                ok_btn.config(state='normal')
                cancel_btn.config(state='normal')

            threading.Thread(target=worker, daemon=True).start()

        def _rename_done(new_name: str):
            dlg.destroy()
            node['name'] = new_name
            par_iid  = self._parent_iid_by_iid.get(iid, '')
            par_full = self.tree_fullname_by_iid.get(par_iid, '') if par_iid else ''
            self._update_fullnames(node, par_full)
            self._save_hierarchy()
            count = node.get('total_nb_images', 0)
            new_full = self.tree_fullname_by_iid[iid]
            if self._filter_var.get().strip():
                self.tree.item(iid, text=new_full)
            else:
                self.tree.item(iid, text=f"{new_name}  ({count:,})")
            for i, (aiid, aname_lower, _) in enumerate(self.tree_all_items):
                updated_full = self.tree_fullname_by_iid.get(aiid)
                if updated_full is not None:
                    self.tree_all_items[i] = (aiid, aname_lower, updated_full)
            self._set_status(f"Renamed album to \"{new_name}\".")
            self._on_mut('rename', int(iid), self.tree_fullname_by_iid[iid])

        ok_btn     = ttk.Button(btn_row, text='Rename', command=_rename)
        cancel_btn = ttk.Button(btn_row, text='Cancel', command=dlg.destroy)
        ok_btn.pack(side='left', padx=(0, 8))
        cancel_btn.pack(side='left')
        entry.bind('<Return>', lambda e: _rename())
        entry.bind('<Escape>', lambda e: dlg.destroy())
        self._center_on_root(dlg)

    # ── Delete ────────────────────────────────────────────────────────────────

    def _do_delete(self, iid: str):
        node  = self._node_by_iid[iid]
        short = node['name']
        if not messagebox.askyesno(
                'Delete Album',
                f"Delete the empty album \"{short}\"?\n\nThis cannot be undone.",
                parent=self.root):
            return

        def worker():
            try:
                c = self._make_client()
                c.delete_album(int(iid))
                c.logout()
                self.root.after(0, _delete_done)
            except Exception as e:
                self.root.after(0, lambda e=e:
                    messagebox.showerror('Error', str(e), parent=self.root))

        def _delete_done():
            par_iid = self._parent_iid_by_iid.get(iid, '')
            if par_iid:
                self._remove_from_list(self._node_by_iid[par_iid]['children'], node['id'])
            else:
                self._remove_from_list(self._hierarchy, node['id'])
            self._save_hierarchy()
            self.tree.delete(iid)
            self._node_by_iid.pop(iid, None)
            self._parent_iid_by_iid.pop(iid, None)
            self.tree_fullname_by_iid.pop(iid, None)
            self.tree_all_items[:] = [t for t in self.tree_all_items if t[0] != iid]
            self._set_status(f"Deleted album \"{short}\".")
            self._on_mut('delete', int(iid), short)

        threading.Thread(target=worker, daemon=True).start()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _make_client(self) -> "AlbumHierarchy.PiwigoClient":
        params = AlbumHierarchy.load_params()
        c = AlbumHierarchy.PiwigoClient(
            params['url'], params['username'], params['password'],
            verify_ssl=params.get('verify_ssl', True),
            rate_limit_calls_per_second=params.get('rate_limit_calls_per_second', 2.0))
        c.login(params['username'], params['password'])
        return c

    def _save_hierarchy(self):
        with open(AlbumHierarchy._album_hierarchy_file(), 'w', encoding='utf-8') as f:
            json.dump(self._hierarchy, f, indent=2, ensure_ascii=False)

    def _update_fullnames(self, node: dict, par_fullname: str):
        node['fullname'] = (f"{par_fullname} / {node['name']}"
                            if par_fullname else node['name'])
        self.tree_fullname_by_iid[str(node['id'])] = node['fullname']
        for child in node.get('children', []):
            self._update_fullnames(child, node['fullname'])

    @staticmethod
    def _remove_from_list(lst: list, node_id: int) -> bool:
        for i, n in enumerate(lst):
            if n['id'] == node_id:
                del lst[i]
                return True
        return False

    # ── Album drag detection (drag-start only; PE handles the rest) ───────────

    _ATW_DRAG_THRESHOLD = 5

    def _on_atw_press(self, event):
        iid  = self.tree.identify_row(event.y)
        elem = self.tree.identify_element(event.x, event.y)
        if iid and elem != 'Treeitem.indicator':
            self._atw_press_pos = (event.x_root, event.y_root)
            self._atw_press_iid = iid
        else:
            self._atw_press_pos = None
            self._atw_press_iid = None

    def _on_atw_motion(self, event):
        if not self._atw_press_pos or not self._atw_press_iid:
            return
        if self._on_album_drag_start is None:
            return
        dx = abs(event.x_root - self._atw_press_pos[0])
        dy = abs(event.y_root - self._atw_press_pos[1])
        if dx < self._ATW_DRAG_THRESHOLD and dy < self._ATW_DRAG_THRESHOLD:
            return
        iid = self._atw_press_iid
        self._atw_press_pos = None
        self._atw_press_iid = None
        try:
            album_id = int(iid)
        except ValueError:
            return
        fullname = self.tree_fullname_by_iid.get(iid, iid)
        self._on_album_drag_start(album_id, fullname, event.x_root, event.y_root)

    def _on_atw_release(self, event):
        self._atw_press_pos = None
        self._atw_press_iid = None

    def _center_on_root(self, dlg: tk.Toplevel):
        self.root.update_idletasks()
        dlg.update_idletasks()
        rw, rh = self.root.winfo_width(),  self.root.winfo_height()
        rx, ry = self.root.winfo_rootx(),  self.root.winfo_rooty()
        dw, dh = dlg.winfo_reqwidth(),     dlg.winfo_reqheight()
        dlg.geometry(f"{dw}x{dh}+{rx+(rw-dw)//2}+{ry+(rh-dh)//2}")
