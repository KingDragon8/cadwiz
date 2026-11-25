# SPDX-License-Identifier: LGPL-2.1-or-later
"""User-selected document authority in the existing CADWiz panel."""
from pathlib import Path


def user_document_operation(session, args):
    """Explicit native user choice; never registered as an assistant tool."""
    previous = session.document_authority
    session.document_authority = None
    result = session.call('document_operation', args)
    if not result.get('ok'):
        session.document_authority = previous
    return result


def choose_working_file(panel):
    widgets = panel.QtWidgets
    session = panel.session()
    document = panel.document()
    if session is None:
        return
    box = widgets.QMessageBox(panel.content)
    box.setWindowTitle('Choose the working document')
    box.setText('Create a separate variant, or explicitly edit the current document.')
    variant = box.addButton('Create variant from a file', widgets.QMessageBox.ActionRole)
    current = box.addButton('Edit current document', widgets.QMessageBox.ActionRole)
    blank = box.addButton('New blank model', widgets.QMessageBox.ActionRole)
    box.addButton(widgets.QMessageBox.Cancel)
    box.exec_()
    if box.clickedButton() is variant:
        source, _ = widgets.QFileDialog.getOpenFileName(panel.content, 'Choose the exact source variant',
                                                       str(Path(document.FileName).parent) if document is not None and document.FileName else '',
                                                       'FreeCAD documents (*.FCStd)')
        if not source:
            return
        destination, _ = widgets.QFileDialog.getSaveFileName(panel.content, 'New variant file',
                                                            str(Path(source).with_name(Path(source).stem + '_variant.FCStd')),
                                                            'FreeCAD documents (*.FCStd)')
        if not destination:
            return
        args = {'mode': 'variant', 'source_path': source, 'target_path': destination}
    elif box.clickedButton() is current and document is not None:
        args = {'mode': 'modify', 'document': document.Name}
    elif box.clickedButton() is blank:
        destination, _ = widgets.QFileDialog.getSaveFileName(panel.content, 'New model file', str(session.project.folder/'New_Model.FCStd'), 'FreeCAD documents (*.FCStd)')
        if not destination:
            return
        args = {'mode': 'new', 'target_path': destination}
    else:
        return
    result = user_document_operation(session, args)
    panel.flash(result.get('say_to_founder', 'Working file selected.'), panel.FOUNDER_BLUE, seconds=8.0)
