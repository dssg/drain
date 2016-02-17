# run this using the following command:
# drain --basedir drain/test/output/ drain/test/test_drain.py::cal
# TODO: add this as an executable test?

from drain import step, model, data
from itertools import product

def calibration():
    steps = []
    for n_estimators, k_folds in product(range(50,300,100), [2,5]):
        d = data.ClassificationData(target=True, n_samples=1000, n_features=100)

        est = step.Construct('sklearn.ensemble.RandomForestClassifier',
                n_estimators=n_estimators, name='estimator') 

        fit_est = model.FitPredict(inputs=[est, d], target=True, name='uncalibrated')

        cal = step.Construct('sklearn.calibration.CalibratedClassifierCV', cv=k_folds,
                inputs=[est], inputs_mapping=['base_estimator'], name='calibrator')

        cal_est = model.FitPredict(inputs=[cal, d], target=True, name='calibrated')

        metrics = model.PrintMetrics([
                {'metric':'baseline'},
                {'metric':'precision', 'k':100},
                {'metric':'precision', 'k':200},
                {'metric':'precision', 'k':300},
        ], inputs=[cal_est], target=True)

        steps.append(fit_est)
        steps.append(metrics)

    return steps

def product():
    d = data.ClassificationData(target=True, n_samples=1000, n_features=100)
    est = step.Construct('sklearn.ensemble.RandomForestClassifier',
                n_estimators=10, name='estimator')

    m1 = model.FitPredict(inputs=[est, d], target=True, name='m1')
    m2 = model.FitPredict(inputs=[est, d], target=True, name='m2')

    p = model.PredictProduct(inputs=[m1,m2], target=True, inputs_mapping=['m1', 'm2'], name='p')

    return p
