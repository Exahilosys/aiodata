# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
# import os
# import sys
# sys.path.insert(0, os.path.abspath('.'))


# -- Project information -----------------------------------------------------
project = 'aiodata'
author = 'Exahilosys'
copyright = f'2019, {author}'

master_doc = 'index'

rst_prolog = ''

# The full version, including alpha/beta/rc tags

package = __import__('pkg_resources').require(project)[0]

metadata = {
    key.rstrip(':'): value
    for (key, value)
    in (
        parts
        for parts
        in (
            line.split(' ', 1)
            for line
            in package.get_metadata_lines(
                package.PKG_INFO
            )
        )
        if len(parts) == 2
    )
    if key.endswith(':')
}

version = metadata['Version']

try:

    pyversion = metadata['Requires-Python']

except KeyError:

    pass

else:

    rst_prolog += f'\n.. |pyversion| replace:: {pyversion}'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.autosectionlabel'
]

# autodoc

autodoc_member_order = 'bysource'

add_module_names = False

autodoc_inherit_docstrings = False

# intersphinx
intersphinx_mapping = {
  'py': ('https://docs.python.org/3', None),
  'wrapio': ('https://wrapio.readthedocs.io/en/latest/', None)
}

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']


# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = 'sphinx_rtd_theme'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# Finalize

def setup(app):

    # Monkey Patching

    import inspect
    import sphinx.ext.autodoc

    old_add_line = sphinx.ext.autodoc.ClassDocumenter.add_line

    def new_add_line(self, line, source, *lineno):

        name = inspect.stack()[1].function

        if name == 'add_directive_header':

            if ':class:`object`' in line:

                return

            if 'Bases:' in line:

                (base, *rest) = self.modname.split('.', 1)

                line = line.replace(base, '~' + base)

        return old_add_line(self, line, source, *lineno)

    sphinx.ext.autodoc.ClassDocumenter.add_line = new_add_line
