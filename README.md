#drain

Drain integrates Python machine learning tasks with [drake](https://github.com/Factual/drake), resulting in a robust and efficient machine learning pipeline. Drain additionally provides a library of methods for both the processing data going into the pipeline and exploration of models coming out of the pipeline.

## Inputs Mapping

The `inputs_mapping` argument to a step allows for convenience and flexibility in passing that step's inputs' results to the step's `run()` method.

### Default behavior

By default, results are passed as positional arguments. So a step with `inputs=[a, b]` will have `run` called as
```
run(a.get_result(), b.get_result())
```

When a step produces multiple items as the result of run() it is often useful to name them and return them as a dictionary. Dictionary results are merged (with later inputs overriding earlier ones?) and passed to `run` as keyword arguments. So if inputs `a` and `b` had dictionary results with keys `a_0, a_1` and `b_0, b_1`, respectively, then `run` will be called as

```
run(a_0=a.get_result()['a_0'], a_1=a.get_result()['a_1'],
    b_0=a.get_result()['b_0'], b_1=b.get_result()['b_1'])
```

### Custom behavior
This mapping of input results to run arguments can be customized when constructing steps. For example if the results of `a` and `b` are objects then specifying
```
inputs_mapping = ['a', 'b']
```
will result in the call
```
run(a=a.get_result(), b=b.get_result()
```
If `a` and `b` return dicts then the mapping can be used to change their keywords or exclude the values:
```
inputs_mapping = [{'a_0':'alpha_0', 'a_1': None}, {'b_1':'beta_1'}]
```
will result in the call
```
run(alpha_0=a.get_result()['a_0'],
    b_0=a.get_result()['b_0'], beta_1=b.get_result()['beta_1'])
```
where:
- `a_0` and `b_1` have been renamed to `alpha_0` and `alpha_1`, respectively
- `a_1` has been excluded, and
- `b_0` has been preserved.

To ignore the inputs mapping simply define
```
def run(self, *args, **kwargs):
    results = [i.get_result() for i in self.inputs]
```

## explore

## Future improvements
option to store in db instead of files
