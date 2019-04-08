import eqsig
from eqsig import duhamels
import numpy as np

import openseespy.opensees as opy
import openseespy.wrap as opw


def get_inelastic_response(mass, k_spring, f_yield, motion, dt, xi=0.05, r_post=0.0):
    """
    Run seismic analysis of a nonlinear SDOF

    :param mass: SDOF mass
    :param k_spring: spring stiffness
    :param f_yield: yield strength
    :param motion: list, acceleration values
    :param dt: float, time step of acceleration values
    :param xi: damping ratio
    :param r_post: post-yield stiffness
    :return:
    """
    osi = opw.OpenseesInstance(dimensions=2)

    # Establish nodes
    bot_node = opw.nodes.Node(osi, 0, 0)
    top_node = opw.nodes.Node(osi, 0, 0)

    # Fix bottom node
    opy.fix(top_node.tag, opw.static.FREE, opw.static.FIXED, opw.static.FIXED)
    opy.fix(bot_node.tag, opw.static.FIXED, opw.static.FIXED, opw.static.FIXED)
    # Set out-of-plane DOFs to be slaved
    opy.equalDOF(top_node.tag, bot_node.tag, *[opw.static.Y, opw.static.ROTZ])

    # nodal mass (weight / g):
    opy.mass(top_node.tag, mass, 0., 0.)

    # Define material
    bilinear_mat = opw.uniaxial_materials.Steel01(osi, fy=f_yield, e0=k_spring, b=r_post)

    # Assign zero length element, # Note: pass actual node and material objects into element
    opw.elements.ZeroLength(osi, bot_node, top_node, mat_x=bilinear_mat, r_flag=1)

    # Define the dynamic analysis
    load_tag_dynamic = 1
    pattern_tag_dynamic = 1

    values = list(-1 * motion)  # should be negative
    opy.timeSeries('Path', load_tag_dynamic, '-dt', dt, '-values', *values)
    opy.pattern('UniformExcitation', pattern_tag_dynamic, opw.static.X, '-accel', load_tag_dynamic)

    # set damping based on first eigen mode
    angular_freq = opy.eigen('-fullGenLapack', 1) ** 0.5
    beta_k = 2 * xi / angular_freq
    opw.rayleigh.Rayleigh(osi, alpha_m=0.0, beta_k=beta_k, beta_k_init=0.0, beta_k_comm=0.0)

    # Run the dynamic analysis

    opy.wipeAnalysis()

    opw.algorithms.Newton(osi)
    opy.system('SparseGeneral')
    opy.numberer('RCM')
    opy.constraints('Transformation')
    opy.integrator('Newmark', 0.5, 0.25)
    opy.analysis('Transient')

    opw.test_checks.EnergyIncr(osi, tol=1.0e-10, max_iter=10)
    analysis_time = (len(values) - 1) * dt
    analysis_dt = 0.001
    outputs = {
        "time": [],
        "rel_disp": [],
        "rel_accel": [],
        "rel_vel": [],
        "force": []
    }

    while opy.getTime() < analysis_time:
        curr_time = opy.getTime()
        opy.analyze(1, analysis_dt)
        outputs["time"].append(curr_time)
        outputs["rel_disp"].append(opy.nodeDisp(top_node.tag, opw.static.X))
        outputs["rel_vel"].append(opy.nodeVel(top_node.tag, opw.static.X))
        outputs["rel_accel"].append(opy.nodeAccel(top_node.tag, opw.static.X))
        opy.reactions()
        outputs["force"].append(-opy.nodeReaction(bot_node.tag, opw.static.X))  # Negative since diff node
    opy.wipe()
    for item in outputs:
        outputs[item] = np.array(outputs[item])

    return outputs


def test_sdof():
    """
    Create a plot of an elastic analysis, nonlinear analysis and closed form elastic

    :return:
    """

    from tests.conftest import TEST_DATA_DIR

    record_path = TEST_DATA_DIR
    record_filename = 'test_motion_dt0p01.txt'
    dt = 0.01
    rec = np.loadtxt(record_path + record_filename)
    acc_signal = eqsig.AccSignal(rec, dt)
    period = 1.0
    xi = 0.05
    mass = 1.0
    f_yield = 1.5  # Reduce this to make it nonlinear
    r_post = 0.0

    periods = np.array([period])
    resp_u, resp_v, resp_a = duhamels.response_series(motion=rec, dt=dt, periods=periods, xi=xi)

    k_spring = 4 * np.pi ** 2 * mass / period ** 2
    outputs = get_inelastic_response(mass, k_spring, f_yield, rec, dt, xi=xi, r_post=r_post)
    outputs_elastic = get_inelastic_response(mass, k_spring, f_yield * 100, rec, dt, xi=xi, r_post=r_post)
    ux_opensees = outputs["rel_disp"]
    disp_inelastic_final = ux_opensees[-1]

    time = acc_signal.time
    acc_opensees_elastic = np.interp(time, outputs_elastic["time"], outputs_elastic["rel_accel"]) - rec
    ux_opensees_elastic = np.interp(time, outputs_elastic["time"], outputs_elastic["rel_disp"])
    diff_disp = abs(np.sum(ux_opensees_elastic - resp_u[0]))
    diff_acc = abs(np.sum(acc_opensees_elastic - resp_a[0]))
    assert diff_disp < 1.0e-4
    assert diff_acc < 5.0e-4
    assert np.isclose(disp_inelastic_final, 0.0186556)


if __name__ == '__main__':
    test_sdof()
