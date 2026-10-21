# Changing the CADWiz panel's buttons

You have the code, so you can change the CADWiz panel to suit you. Every main
button is described in **one table**, and there is a ready-made place for buttons
of your own. You only need a text editor.

The file is:

```
CADWiz/src/integrations/cadwiz_plugin/slim_panel.py
```

(after installing, it is in FreeCAD's `Mod\CADWiz` folder; on Windows that is
`%APPDATA%\FreeCAD\v1-1\Mod\CADWiz\...`).

## 1. Rename a button or change its tooltip

Find the table that starts with `BUTTONS: dict[str, tuple[str, str, str]] = {`.
Each line is one button:

```python
"show_claude": ("Show Claude", "CADWiz_Show_Claude", "Freeze this picture, your marks, ..."),
#  key          the words on it  its object name       the tooltip
```

Change the **words** or the **tooltip** in quotes. Leave the key and the object
name alone (other code finds the button by them). For example:

```python
"show_claude": ("Ask Claude", "CADWiz_Show_Claude", "Send Claude what I'm looking at"),
```

## 2. Add a button of your own

Just below the table is an empty list called `EXTRA_BUTTONS`. Each entry is
(the words on the button, a tooltip, a FreeCAD command). The command can be any
name from FreeCAD's **Tools > Customize > Commands** list. For example, to add a
**Fit** button that fits the whole model in the view:

```python
EXTRA_BUTTONS: list[tuple[str, str, str]] = [
    ("Fit", "Fit the whole model in the view", "Std_ViewFit"),
]
```

Your buttons appear at the end of the row of view buttons on the **Creating** page.

## 3. See it

Save the file and **restart FreeCAD**. If the panel doesn't appear, open
**View > Panels > Report view**: CADWiz prints the line it could not read there.
Undo your change (or reinstall CADWiz) to get back to the original.

## Going further

Anything a button does lives in the same file. Search for the button's key (for
example `toggle_assembly` for Assembly) to see the code it runs. If you make
something others would like, consider sending it back: see
[CONTRIBUTING.md](../CONTRIBUTING.md).

Changes you make are yours to keep; updating CADWiz replaces the file, so keep a
copy of your edits.
