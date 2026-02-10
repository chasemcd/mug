# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from __future__ import annotations

# -- Path setup --------------------------------------------------------------
# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

sys.path.insert(0, os.path.abspath("../"))


# -- Project information -----------------------------------------------------

project = "mug"
copyright = "2024, Chase McDonald"
author = "Chase McDonald"


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "IPython.sphinxext.ipython_console_highlighting",
    "IPython.sphinxext.ipython_directive",
    "sphinx_copybutton",
]


# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#

html_theme = "sphinx_book_theme"

# https://sphinx-book-theme.readthedocs.io/en/latest/customize/index.html
html_theme_options = {
    "repository_url": "https://github.com/chasemcd/interactive-gym",
    "repository_branch": "main",
    "use_repository_button": True,
    "use_issues_button": True,
    "path_to_docs": "docs/",
    "use_edit_page_button": True,
    # "logo_only": True,
    "show_toc_level": 2,  # Show 2 levels of TOC in sidebar
    "navigation_with_keys": False,
    "collapse_navigation": False,  # Keep navigation expanded
    "navigation_depth": 4,  # Show nested structure
}

# Always show the full global TOC in the sidebar
html_sidebars = {
    "**": ["navbar-logo.html", "sbt-sidebar-nav.html"]
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

# Custom CSS files
html_css_files = [
    "custom.css",
]
