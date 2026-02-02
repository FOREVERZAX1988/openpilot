#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_6160433194432564726);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_2084276865667981673);
void pose_H_mod_fun(double *state, double *out_4530868877997210395);
void pose_f_fun(double *state, double dt, double *out_659554858487434793);
void pose_F_fun(double *state, double dt, double *out_8122516567546015023);
void pose_h_4(double *state, double *unused, double *out_8968392969190010627);
void pose_H_4(double *state, double *unused, double *out_3406733573803791520);
void pose_h_10(double *state, double *unused, double *out_4778739924469370119);
void pose_H_10(double *state, double *unused, double *out_4773808119150424256);
void pose_h_13(double *state, double *unused, double *out_8774561321168379953);
void pose_H_13(double *state, double *unused, double *out_194459748471458719);
void pose_h_14(double *state, double *unused, double *out_4087694789546319597);
void pose_H_14(double *state, double *unused, double *out_3841850100448675119);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}