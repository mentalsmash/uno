###############################################################################
# (C) Copyright 2020 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of the 
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################
import pathlib
from types import SimpleNamespace

import jinja2

from libuno.yml import repr_yml, yml

import libuno.log
logger = libuno.log.logger("uvn.tmplt")

class UvnTemplates:
    _instance = None

    def __init__(self):
        self._env = jinja2.Environment(
            loader=jinja2.PackageLoader("libuno", package_path="templates"),
            autoescape=jinja2.select_autoescape(['html', 'xml']))
    
    @staticmethod
    def instance():
        if UvnTemplates._instance is None:
           UvnTemplates._instance = UvnTemplates()
        return UvnTemplates._instance 
    
    def template(self, name):
        return self._env.get_template(name)

    def generate(self, template, ctx):
        tmplt = self.template(template)
        return tmplt.generate(**ctx)
    
    def render(self, template, ctx, inline=False):
        if inline:
            tmplt = tmplt = jinja2.Template(template)
        else:
            tmplt = self.template(template)
        return tmplt.render(**ctx)


Representations = SimpleNamespace()
Representations.yml = "_yml"

class TemplateError(Exception):
    def __init__(self, msg):
        self.msg = msg

def TemplateRepresentation(repr, tmplt):
    if (not isinstance(repr, str) or len(repr) == 0 or repr[0] == "_"):
        raise TemplateError("invalid representation name: {}".format(repr))
    
    if (not isinstance(tmplt, str) or len(tmplt) == 0):
        raise TemplateError("invalid template name: {}".format(tmplt))
    
    def template_generator(cls):
        TemplateRenderer._class_renderer_assert(cls)
        TemplateRenderer._class_representations_add(cls, repr, tmplt)
        return cls
    return template_generator

class TemplateRenderer:
    _instance = None

    _class_representations_attr = "_tmplt_reprs"
    _class_renderer_attr = "_tmplt_rendr"
    _class_renderer_name = "_TemplateRenderer"

    @staticmethod
    def _class_renderer_assert(cls):
        rendr = getattr(cls, TemplateRenderer._class_renderer_attr, None)
        if rendr is None:
            rendr_cls = getattr(cls, TemplateRenderer._class_renderer_name, None)
            if rendr_cls is None:
                rendr_cls = TemplateRenderer
            rendr = rendr_cls()
            try:
                setattr(cls, TemplateRenderer._class_renderer_attr, rendr)
            except Exception as e:
                # assume we tried to set attribute on a built-in type
                pass
        if (not isinstance(rendr, TemplateRenderer)):
            raise TemplateError(
                "invalid template renderer for class: {}".format(cls))
        return rendr
    
    @staticmethod
    def _class_representations_assert(cls):
        reprs = getattr(cls, TemplateRenderer._class_representations_attr, None)
        if reprs is None:
            reprs = {}
            try:
                setattr(cls, TemplateRenderer._class_representations_attr, reprs)
            except Exception as e:
                # assume we tried to set attribute on a built-in type
                pass
        return reprs
    
    @staticmethod
    def _class_representations_add(cls, repr, tmplt):
        cls_reprs = TemplateRenderer._class_representations_assert(cls)
        cls_reprs[repr] = tmplt
    
    def _file_write(self, file, contents, append):
        if (isinstance(file, str)):
            file = pathlib.Path(file)
        if (append):
            f_mode = "a"
        else:
            f_mode = "w"
        
        parent_dir = file.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        with file.open(f_mode) as outfile:
            outfile.write(contents)
    
    def repr_ctx(self, obj, repr, repr_tmplt, **kwargs):
        return repr_yml(obj, repr=repr, repr_tmplt=repr_tmplt, **kwargs)
    
    def repr_tmplt(self, obj, repr):
        cls_reprs = TemplateRenderer._class_representations_assert(obj.__class__)
        repr_tmplt = cls_reprs.get(repr)
        if repr_tmplt is None:
            raise TemplateError(
                    "unknown template representation for {}: {}".format(
                        obj.__class__, repr))
        return repr_tmplt
    
    def render_yml(self, obj, **kwargs):
        return yml(obj, **kwargs)
    
    def render(self, obj, repr,
            to_file=None, append_to_file=False,
            context=None, inline=False,
            **kwargs):
        if inline:
            repr_tmplt = repr
        else:
            repr_tmplt = self.repr_tmplt(obj, repr)
            logger.debug("[render] {} -> {}", repr, repr_tmplt)

        tmplt_ctx = self.repr_ctx(obj, repr, repr_tmplt, **kwargs)
        if context is not None:
            tmplt_ctx.update(context)

        templates = UvnTemplates.instance()

        rendered = templates.render(repr_tmplt, tmplt_ctx, inline=inline)
        logger.trace("[rendered] {} + {} =\n{}", repr_tmplt, tmplt_ctx, rendered)

        if to_file is not None:
            self._file_write(to_file, rendered, append_to_file)
        
        return rendered

def render_yml(obj, **kwargs):
    return render(obj, Representations.yml, **kwargs)

def render(obj, repr, **kwargs):
    rendr = TemplateRenderer._class_renderer_assert(obj.__class__)
    if repr == Representations.yml:
        return rendr.render_yml(obj, **kwargs)
    else:
        return rendr.render(obj, repr, **kwargs)
