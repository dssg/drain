import os
import datetime
import math
from copy import deepcopy

import pandas as pd
import numpy as np
from statsmodels.discrete.discrete_model import Logit
from drain import util, metrics

class ModelRun(object):
    def __init__(self, estimator, y, data):
        self.estimator = estimator
        self.y = y
        self.data = data

def y_score(estimator, X):
    if hasattr(estimator, 'decision_function'):
        return estimator.decision_function(X)
    else:
        y = estimator.predict_proba(X)
        return y[:,1]

# given a params dict and a basedir and a method, return a directory for storing the method output
# generally this is basedir/method/#/
# where '#' is the hash of the yaml dump of the params dict
# in the special case of method='model', the metrics key is dropped before hashing
def params_dir(basedir, params, method):
    if method == 'model' and 'metrics' in params:
        params = deepcopy(params)
        params.pop('metrics')

    h = util.hash_yaml_dict(params)
    d = os.path.join(basedir, method, h + '/')
    return d

def sk_tree(X,y, params={'max_depth':3}):
    clf = tree.DecisionTreeClassifier(**params)
    return clf.fit(X, y)

def feature_importance(estimator, X):
    if hasattr(estimator, 'coef_'):
        i = estimator.coef_[0]
    elif hasattr(estimator, 'feature_importances_'):
        i = estimator.feature_importances_
    else:
        i = [np.nan]*len(X.columns)

    return pd.DataFrame({'feature': X.columns, 'importance': i}).sort_values('importance', ascending=False)


class LogisticRegression(object):
    def __init__(self):
        pass

    def fit(self, X, y, **kwargs):
        self.model = Logit(y, X)
        self.result = self.model.fit()
    
    def predict_proba(self, X):
        return self.result.predict(X)

from sklearn.externals.joblib import Parallel, delayed
from sklearn.ensemble.forest import _parallel_helper

def _proximity_parallel_helper(train_nodes, t, k):
    d = (train_nodes == t).sum(axis=1)
    n = d.argsort()[::-1][:k]
    
    return d[n], n #distance, neighbors

def _proximity_helper(train_nodes, test_nodes, k):
    results = Parallel(n_jobs=16, backend='threading')(delayed(_proximity_parallel_helper)(train_nodes, t, k) for t in test_nodes)
    distance, neighbors = zip(*results)
    return np.array(distance), np.array(neighbors)

# store nodes in run
def apply_forest(run):
    run['nodes'] = pd.DataFrame(run.estimator.apply(run['data'].X), index=run['data'].X.index)
    
# look for nodes in training set proximal to the given nodes
def proximity(run, ix, k):
    if 'nodes' not in run:
        apply_forest(run)
    distance, neighbors = _proximity_helper(run['nodes'][run.y.train].values, run['nodes'].loc[ix].values, k)
    neighbors = run['nodes'][run.y.train].irow(neighbors.flatten()).index
    neighbors = [neighbors[k*i:k*(i+1)] for i in range(len(ix))]
    return distance, neighbors

# subset a model "y" dataframe
# dropna means drop missing outcomes
# return top k (count) or p (proportion) if specified
# p_dropna means proportion is relative to labeled count
def y_subset(y, masks=[], filters={}, test=True, 
        dropna=False, outcome='true',
        k=None, p=None, ascending=False, score='score', p_dropna=True):

    masks2=[]
    for mask in masks:
        masks2.append(util.get_series(y, mask))

    for column, value in filters.iteritems():
        masks2.append(util.get_series(y, column) == value)

    if test:
        masks2.append(y['test'])

    mask = util.intersect(masks2)
    y = y[mask]

    if dropna:
        y = y.dropna(subset=[outcome])

    if k is not None and p is not None:
        raise ValueError("Cannot specify both k and p")
    elif k is not None:
        k = k
    elif p is not None:
        k = int(p*metrics.count(y[outcome], dropna=p_dropna))
    else:
        k = None

    if k is not None:
        y = y.sort_values(score, ascending=ascending).head(k)

    return y

def true_score(y, outcome='true', score='score', **subset_args):
    y = y_subset(y, outcome=outcome, score=score, **subset_args) 
    return util.to_float(y[outcome], y[score])

def auc(run, dropna=True, **subset_args):
    y_true, y_score = true_score(run.y, dropna=True, **subset_args)
    return metrics.auc(y_true, y_score)

# return size of dataset
# if dropna=True, only count rows where outcome is not nan
# note this means witholdinging dropna from y_subset() call
def count(run, dropna=False, **subset_args):
    y_true,y_score = true_score(run.y, **subset_args)
    return metrics.count(y_true, dropna=dropna)

def baseline(run, **subset_args):
    y_true,y_score = true_score(run.y, **subset_args)
    return metrics.baseline(y_true)

def precision(run, return_bounds=True, dropna=True, **subset_args):
    y_true, y_score = true_score(run.y, dropna=dropna, **subset_args)

    return metrics.precision_at_k(y_true, y_score, len(y_true), return_bounds=return_bounds, extrapolate=(not dropna))

def precision_series(run, **subset_args):
    y_true, y_score = true_score(run.y, **subset_args)
    return metrics.precision_series(y_true, y_score)

def recall(run, value=True, **subset_args):
    y_true, y_score = true_score(run.y, **subset_args)
    return metrics.recall(y_true, y_score, value=value)

def recall_series(run, value=True, **subset_args):
    y_true, y_score = true_score(run.y, **subset_args)
    return metrics.recall_series(y_true, y_score, value=value)

# TODO: should these metrics be member methods of ModelRun? e.g.:
# ModelRun.recall = recall
