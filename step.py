import yaml
import sys
import itertools
import pandas as pd
from pprint import pformat
from StringIO import StringIO
from sklearn.base import _pprint
import joblib
import os
import base64
import hashlib
import itertools
import logging

from . import util

#from model import SklearnEstimatorStep

# TODO:
#    - random grid search
#    - get steps by name
#    - optional args like njobs that don't affect output? allow them to be excluded from yaml, hash, eq
#    - don't initialize yaml twice

BASEDIR=None

# run the given step
# inputs should be loaded from disk
# output should be written to disk
def run(step, inputs=None, output=None):
    if inputs is None:
        inputs = []
    if output is None:
        output = []

    if not step.has_result():
        if step in inputs:
            step.set_result(step.load())
        else:
            for i in step.inputs:
                run(step=i, inputs=inputs, output=output)

            args, kwargs = step.map_inputs()
            logging.info('Running\n\t%s' % str(step).replace('\n','\n\t'))
            step.set_result(step.run(*args, **kwargs))

    if step == output:
        step.dump()
        util.touch(step.get_target_filename())

    return step.get_result()

def from_yaml(filename):
    with open(filename) as f:
        templates = yaml.load(f)
        if isinstance(templates, Step):
            return templates._template_construct()
        elif hasattr(templates, '__iter__'):
            return [t._template_construct() for t in templates]
        else:
            return templates

class Step(object):
    def __init__(self, name=None, target=False, **kwargs):
        self.__kwargs__ = kwargs
        self.__name__ = name
        self.__target__ = target

        for k in kwargs:
            setattr(self, k, kwargs[k])
        
        if 'inputs' not in kwargs:
            self.inputs = []

        hasher = hashlib.md5(yaml.dump(self)) # this won't work right if we haven't called initialize()
        self.__digest__ = base64.urlsafe_b64encode(hasher.digest())

    @staticmethod
    def _template(__cls__=None, **kwargs):
        if __cls__ is None:
            __cls__ = Step
        self = Step.__new__(__cls__)
        self.__template__ = StepTemplate(**kwargs)
        return self

    def _is_template(self):
        return hasattr(self, '__template__')

    def _template_construct(self):
        if self._is_template():
            template = self.__template__

            if 'inputs' in template.kwargs:
                for i in template.kwargs['inputs']:
                    i._template_construct()

            self.__init__(target=template.target, name=template.name, **template.kwargs)
            del self.__template__
            return self

    def _template_copy(self, **kwargs):
        if not self._is_template():
            raise ValueError('Cannot copy, this is not a template')

        template = self.__template__
        kwargs = util.merge_dicts(template.kwargs, kwargs)
        return Step._template(__cls__=self.__class__, name=template.name, target=template.target, **kwargs)

    # search over self and inputs to return a dictionary of name: step pairs
    def get_named_steps(self, named=None, visited=None):
        if visited is None:
            visited = set()
        if named is None:
            named = dict()

        for i in self.inputs:
            if i not in visited:
                i.get_named_steps(named=named, visited=visited)
        
        if self.has_name():
            name = self.get_name()
            if name in named:
                raise NameError('Multiple steps with the same name: %s' % name)
            named[name] = self

        visited.add(self)

        return named

    def get_name(self):
        return self.__name__

    def has_name(self):
        return self.__name__ is not None

    def get_named_arguments(self):
        d = dict()
        named = self.get_named_steps()

        for name, step in named.iteritems():
            for k,v in step.get_arguments(ignore_inputs=True).iteritems():
                d[(name, k)] = v

        return d

    # returns a shallow copy
    def get_arguments(self, ignore_inputs=False):
        d = dict(self.__kwargs__)
        if ignore_inputs:
            for k in ('inputs', 'inputs_mapping'):
                if k in d:
                    d.pop(k)

        return d

    def map_inputs(self):
        kwargs = {}
        args = []

        if hasattr(self, 'inputs_mapping'):
            inputs_mapping = util.make_list(self.inputs_mapping)
        
            for input, mapping in zip(self.inputs, inputs_mapping):
                if isinstance(mapping, dict):
                    for k in mapping:
                        kwargs[k] = input.get_result()[mapping[k]]
                elif isinstance(mapping, basestring):
                    kwargs[mapping] = input.get_result()
                else:
                    raise ValueError('Input mapping is neither dict nor str: %s' % mapping)

        else:
            # without a mapping we handle two cases
            for result in [i.get_result() for i in self.inputs]:
                # when the result is a dict merge it with a global dict
                if isinstance(result, dict):
                    kwargs.update(result)
                # otherwise use it as a positional argument
                else:
                    args.append(result)

        return args, kwargs

    def get_result(self):
        return self.__result__

    def set_result(self, result):
        self.__result__ = result

    def has_result(self):
        return hasattr(self, '__result__')

    def get_dirname(self):
        if BASEDIR is None:
            raise ValueError('BASEDIR not initialized')

        return os.path.join(BASEDIR, self.__class__.__name__, self.__digest__[0:8])

    def get_yaml_filename(self):
        return os.path.join(self.get_dirname(), 'step.yaml')

    def get_dump_dirname(self):
        return os.path.join(self.get_dirname(), 'dump')

    def get_target_filename(self):
        return os.path.join(self.get_dirname(), 'target')
        
    def run(self):
        raise NotImplementedError()
    
    def is_target(self):
        return self.__target__
    
    def load(self, **kwargs):
        return joblib.load(os.path.join(self.get_dirname(), 'dump', 'result.pkl'), **kwargs)

    def setup_dump(self):
        dumpdir = self.get_dump_dirname()
        if not os.path.isdir(dumpdir):
            os.makedirs(dumpdir)
            
        dump = False
        yaml_filename = self.get_yaml_filename()
        
        if not os.path.isfile(yaml_filename):
            dump = True
        else:
            with open(yaml_filename) as f:
                if f.read() != yaml.dump(self):
                    logging.warning('Existing step.yaml does not match hash, regenerating')
                    dump = True
        
        if dump:
            with open(yaml_filename, 'w') as f:
                yaml.dump(self, f)

    def dump(self, **kwargs):
        self.setup_dump()
        joblib.dump(self.get_result(), os.path.join(self.get_dump_dirname(), 'result.pkl'), **kwargs)

    def get_kwargs(self, deep=True):
        if deep:
            return self.__kwargs__
        else:
            kwargs = dict(self.__kwargs__)
            if 'inputs' in kwargs:
                kwargs.pop('inputs')
            return kwargs

    def __repr__(self):
        class_name = self.__class__.__name__
        if self._is_template():
            class_name += 'Template'
            kwargs = self.__template__.kwargs
        else:
            kwargs = self.get_kwargs(deep=False)

        return '%s(%s)' % (class_name, 
                _pprint(kwargs, offset=len(class_name)),)
    
    def __hash__(self):
        return hash(yaml.dump(self)) # pyyaml dumps dicts in sorted order so this works
    
    def __eq__(self, other):
        if not isinstance(other, Step):
            return False
        elif self._is_template() and other._is_template():
            return util.eqattr(self, other, '__class__') and util.eqattr(self, other, '__template__')
        elif not self._is_template() and not other._is_template():
            return util.eqattr(self, other, '__class__') and util.eqattr(self, other, '__kwargs__')
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

class Construct(Step):
    def __init__(self, __class_name__, name=None, target=None, **kwargs):
        Step.__init__(self, __class_name__=__class_name__, name=name, target=target, **kwargs)

    def run(self, **update_kwargs):
        kwargs = dict(self.__kwargs__)
        for k in ['inputs', 'inputs_mapping']:
            if k in kwargs:
                kwargs.pop(k)
        kwargs.update(update_kwargs)
        cls = util.get_attr(kwargs.pop('__class_name__'))
        return cls(**kwargs)

# temporary holder of step arguments
# used to expand ArgumentCollections by search()
# and to set inputs by serial()
class StepTemplate(object):
    def __init__(self, name=None, target=False, **kwargs):
        self.name = name
        self.target = target
        self.kwargs = kwargs

    def __eq__(self, other):
        return util.eqattr(self, other, 'name') and util.eqattr(self, other, 'target') and util.eqattr(self, other, 'kwargs')

    def __ne__(self, other):
        return not self.__eq__(other)

class Echo(Step):
    def run(self, *args, **kwargs):
        for i in self.inputs:
            print('%s: %s' % (i, i.get_result()))


class Scalar(Step):
    def __init__(self, value, **kwargs):
        Step.__init__(self, value=value, **kwargs)

    def run(self, *values):
        return self.value

class Add(Step):
    def run(self, *values):
        return sum(values)

class Divide(Step):
    def run(self, numerator, denominator):
        return numerator / denominator
        
class ArgumentCollection(object):
    def __init__(self, collection):
        if not hasattr(collection, '__iter__'):
            raise ValueError('Not a collection: %s' % collection)
        self.collection = collection    

def argument_product(args):
    for k in args:
        if isinstance(args[k], dict):
            args[k] = ArgumentCollection(argument_product(args[k]))
    
    product_vars = [k for k in args if isinstance(args[k], ArgumentCollection)]
    for k in product_vars:
        args[k] = args[k].collection
    dicts = util.dict_product(args, product_vars)
    return dicts

def step_product(step):
    return [step._template_copy(**d) for d in argument_product(step.__template__.kwargs)]

def parallel(*inputs):
    return map(util.make_list, itertools.chain(*map(util.make_list, inputs)))

def search(*inputs):
    return list(itertools.chain(*map(util.make_list, map(step_product, inputs))))

# compose the list of steps by setting s(n).inputs = s(n-1)
def serial(*inputs):
    psteps = None
    for steps in map(util.make_list, inputs):
        if psteps is not None:
            if not hasattr(psteps[0], '__iter__'):
                psteps = (psteps,)
            steps = list(itertools.chain(*(map(lambda s: s._template_copy(inputs=util.make_list(ps)), steps) for ps in psteps)))
            
        psteps = steps
    return psteps
    
# take the product of steps from each step
def product(*inputs):
    return list(itertools.product(*map(util.make_list, inputs)))
    
def step_multi_representer(dumper, data):
    tag = '!step:%s.%s' % (data.__class__.__module__, data.__class__.__name__)
    return dumper.represent_mapping(tag, data.__kwargs__)

def step_multi_constructor(loader, tag_suffix, node):
    cls = util.get_attr(tag_suffix[1:])
    kwargs = loader.construct_mapping(node)

    return Step._template(__cls__=cls, **kwargs)

def constructor_multi_constructor(loader, tag_suffix, node):
    class_name = tag_suffix[1:]
    kwargs = loader.construct_mapping(node)

    return Step._template(__cls__=Construct, __class_name__=str(class_name), **kwargs)

def get_sequence_constructor(method):
    def constructor(loader, node):
        seq = loader.construct_sequence(node)
        return method(*seq)
    return constructor

def range_constructor(loader, node):
    args = loader.construct_sequence(node)
    return ArgumentCollection(xrange(*args))

def list_constructor(loader, node):
    args = loader.construct_sequence(node)
    return ArgumentCollection(args)

def powerset_constructor(loader, node):
    args = loader.construct_sequence(node)
    return ArgumentCollection(itertools.chain.from_iterable(itertools.combinations(args, r) for r in range(len(args)+1)))

def initialize(basedir):
    global BASEDIR
    BASEDIR = basedir
    yaml.add_multi_representer(Step, step_multi_representer)
    yaml.add_multi_constructor('!step', step_multi_constructor)
    yaml.add_multi_constructor('!construct', constructor_multi_constructor)
    
    yaml.add_constructor('!parallel', get_sequence_constructor(parallel))
    yaml.add_constructor('!search', get_sequence_constructor(search))
    yaml.add_constructor('!serial', get_sequence_constructor(serial))
    yaml.add_constructor('!product', get_sequence_constructor(product))

    yaml.add_constructor('!range', range_constructor)
    yaml.add_constructor('!powerset', powerset_constructor)
    yaml.add_constructor('!list', list_constructor)

def get_targets(step, ignore):
    outputs = set()
    if not ignore and step.is_target():
        outputs.add(step)
    else:
        for i in step.inputs:
            outputs.update(get_targets(i, False))

    return outputs

def get_input_targets(step):
    return get_targets(step, ignore=True)

def get_output_targets(step):
    return get_targets(step, ignore=False)

# returns three Step:set<Step> dicts
# output_inputs: maps output to inputs
# output_no_outputs: maps output to no-outputs that depend on it (for no-output steps with single target input)
# no_output_inputs: maps no_output step with *multiple* target inputs to them
def get_drake_data_helper(steps):
    output_inputs = {}
    output_no_outputs = {}
    no_output_inputs = {}

    for step in steps:
        if step.is_target():
            if step not in output_inputs:
                output_inputs[step] = get_input_targets(step)
        else:
            outputs = get_output_targets(step)
            no_output_inputs[step] = outputs

    # recursively do the same for all the inputs
    inputs = set()
    for i in itertools.chain(output_inputs.values(), no_output_inputs.values()):
        inputs |= i

    if len(inputs) > 0:
        o1, o2 = get_drake_data_helper(inputs)
        util.dict_update_union(output_inputs, o1)
        util.dict_update_union(no_output_inputs, o2)


    return output_inputs, no_output_inputs

# returns data for the drakefile
# i.e. a list of tuples (inputs, output, no-outputs)
def get_drake_data(steps):
    drake_data = {}
    output_inputs, no_output_inputs = get_drake_data_helper(steps)
    for output, inputs in output_inputs.iteritems():
        drake_data[output] = inputs

    for no_output, inputs in no_output_inputs.iteritems():
        drake_data[no_output] = inputs

    return drake_data

def to_drake_step(inputs, output):
    inputs = map(lambda i: i.get_target_filename(), list(inputs))
    inputs.insert(0, output.get_yaml_filename())

    output_str = '%' + output.__class__.__name__
    if output.is_target():
        output_str += ', ' + os.path.join(output.get_target_filename())
    return '{output} <- {inputs} [method:drain]\n\n'.format(output=output_str, inputs=str.join(', ', inputs))

# if preview then don't create the dump directories and step yaml files
def to_drakefile(steps, preview=True, debug=False, bindir=None):
    data = get_drake_data(steps)
    drakefile = StringIO()

    bindir = os.path.join(os.path.dirname(__file__), 'bin')
    drakefile.write("drain()\n\tpython %s %s/run_step.py $OUTPUT $INPUTS 2>&1\n\n" % ('-m pdb' if debug else '', bindir))
    for output, inputs in data.iteritems():
        if not preview:
            output.setup_dump()

        drakefile.write(to_drake_step(inputs, output))

    return drakefile.getvalue()
