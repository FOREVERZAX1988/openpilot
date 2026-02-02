#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_3100715809813510988);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_206839512396194863);
void car_H_mod_fun(double *state, double *out_7238493767451163297);
void car_f_fun(double *state, double dt, double *out_6599987440062442270);
void car_F_fun(double *state, double dt, double *out_1903483342698302077);
void car_h_25(double *state, double *unused, double *out_9212279725925637519);
void car_H_25(double *state, double *unused, double *out_2015062080346151082);
void car_h_24(double *state, double *unused, double *out_6502327579757325256);
void car_H_24(double *state, double *unused, double *out_4240769864325019644);
void car_h_30(double *state, double *unused, double *out_1471199090963241656);
void car_H_30(double *state, double *unused, double *out_8931752421837767837);
void car_h_26(double *state, double *unused, double *out_3754708124872083291);
void car_H_26(double *state, double *unused, double *out_1726441238527905142);
void car_h_27(double *state, double *unused, double *out_5806757675114330012);
void car_H_27(double *state, double *unused, double *out_6756989110037342926);
void car_h_29(double *state, double *unused, double *out_6472872358624087301);
void car_H_29(double *state, double *unused, double *out_9004760307557391595);
void car_h_28(double *state, double *unused, double *out_855811060453550849);
void car_H_28(double *state, double *unused, double *out_4359584749082629447);
void car_h_31(double *state, double *unused, double *out_9088944523563259126);
void car_H_31(double *state, double *unused, double *out_2045708042223111510);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}