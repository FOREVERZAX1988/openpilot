#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_6160433194432564726) {
   out_6160433194432564726[0] = delta_x[0] + nom_x[0];
   out_6160433194432564726[1] = delta_x[1] + nom_x[1];
   out_6160433194432564726[2] = delta_x[2] + nom_x[2];
   out_6160433194432564726[3] = delta_x[3] + nom_x[3];
   out_6160433194432564726[4] = delta_x[4] + nom_x[4];
   out_6160433194432564726[5] = delta_x[5] + nom_x[5];
   out_6160433194432564726[6] = delta_x[6] + nom_x[6];
   out_6160433194432564726[7] = delta_x[7] + nom_x[7];
   out_6160433194432564726[8] = delta_x[8] + nom_x[8];
   out_6160433194432564726[9] = delta_x[9] + nom_x[9];
   out_6160433194432564726[10] = delta_x[10] + nom_x[10];
   out_6160433194432564726[11] = delta_x[11] + nom_x[11];
   out_6160433194432564726[12] = delta_x[12] + nom_x[12];
   out_6160433194432564726[13] = delta_x[13] + nom_x[13];
   out_6160433194432564726[14] = delta_x[14] + nom_x[14];
   out_6160433194432564726[15] = delta_x[15] + nom_x[15];
   out_6160433194432564726[16] = delta_x[16] + nom_x[16];
   out_6160433194432564726[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_2084276865667981673) {
   out_2084276865667981673[0] = -nom_x[0] + true_x[0];
   out_2084276865667981673[1] = -nom_x[1] + true_x[1];
   out_2084276865667981673[2] = -nom_x[2] + true_x[2];
   out_2084276865667981673[3] = -nom_x[3] + true_x[3];
   out_2084276865667981673[4] = -nom_x[4] + true_x[4];
   out_2084276865667981673[5] = -nom_x[5] + true_x[5];
   out_2084276865667981673[6] = -nom_x[6] + true_x[6];
   out_2084276865667981673[7] = -nom_x[7] + true_x[7];
   out_2084276865667981673[8] = -nom_x[8] + true_x[8];
   out_2084276865667981673[9] = -nom_x[9] + true_x[9];
   out_2084276865667981673[10] = -nom_x[10] + true_x[10];
   out_2084276865667981673[11] = -nom_x[11] + true_x[11];
   out_2084276865667981673[12] = -nom_x[12] + true_x[12];
   out_2084276865667981673[13] = -nom_x[13] + true_x[13];
   out_2084276865667981673[14] = -nom_x[14] + true_x[14];
   out_2084276865667981673[15] = -nom_x[15] + true_x[15];
   out_2084276865667981673[16] = -nom_x[16] + true_x[16];
   out_2084276865667981673[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_4530868877997210395) {
   out_4530868877997210395[0] = 1.0;
   out_4530868877997210395[1] = 0.0;
   out_4530868877997210395[2] = 0.0;
   out_4530868877997210395[3] = 0.0;
   out_4530868877997210395[4] = 0.0;
   out_4530868877997210395[5] = 0.0;
   out_4530868877997210395[6] = 0.0;
   out_4530868877997210395[7] = 0.0;
   out_4530868877997210395[8] = 0.0;
   out_4530868877997210395[9] = 0.0;
   out_4530868877997210395[10] = 0.0;
   out_4530868877997210395[11] = 0.0;
   out_4530868877997210395[12] = 0.0;
   out_4530868877997210395[13] = 0.0;
   out_4530868877997210395[14] = 0.0;
   out_4530868877997210395[15] = 0.0;
   out_4530868877997210395[16] = 0.0;
   out_4530868877997210395[17] = 0.0;
   out_4530868877997210395[18] = 0.0;
   out_4530868877997210395[19] = 1.0;
   out_4530868877997210395[20] = 0.0;
   out_4530868877997210395[21] = 0.0;
   out_4530868877997210395[22] = 0.0;
   out_4530868877997210395[23] = 0.0;
   out_4530868877997210395[24] = 0.0;
   out_4530868877997210395[25] = 0.0;
   out_4530868877997210395[26] = 0.0;
   out_4530868877997210395[27] = 0.0;
   out_4530868877997210395[28] = 0.0;
   out_4530868877997210395[29] = 0.0;
   out_4530868877997210395[30] = 0.0;
   out_4530868877997210395[31] = 0.0;
   out_4530868877997210395[32] = 0.0;
   out_4530868877997210395[33] = 0.0;
   out_4530868877997210395[34] = 0.0;
   out_4530868877997210395[35] = 0.0;
   out_4530868877997210395[36] = 0.0;
   out_4530868877997210395[37] = 0.0;
   out_4530868877997210395[38] = 1.0;
   out_4530868877997210395[39] = 0.0;
   out_4530868877997210395[40] = 0.0;
   out_4530868877997210395[41] = 0.0;
   out_4530868877997210395[42] = 0.0;
   out_4530868877997210395[43] = 0.0;
   out_4530868877997210395[44] = 0.0;
   out_4530868877997210395[45] = 0.0;
   out_4530868877997210395[46] = 0.0;
   out_4530868877997210395[47] = 0.0;
   out_4530868877997210395[48] = 0.0;
   out_4530868877997210395[49] = 0.0;
   out_4530868877997210395[50] = 0.0;
   out_4530868877997210395[51] = 0.0;
   out_4530868877997210395[52] = 0.0;
   out_4530868877997210395[53] = 0.0;
   out_4530868877997210395[54] = 0.0;
   out_4530868877997210395[55] = 0.0;
   out_4530868877997210395[56] = 0.0;
   out_4530868877997210395[57] = 1.0;
   out_4530868877997210395[58] = 0.0;
   out_4530868877997210395[59] = 0.0;
   out_4530868877997210395[60] = 0.0;
   out_4530868877997210395[61] = 0.0;
   out_4530868877997210395[62] = 0.0;
   out_4530868877997210395[63] = 0.0;
   out_4530868877997210395[64] = 0.0;
   out_4530868877997210395[65] = 0.0;
   out_4530868877997210395[66] = 0.0;
   out_4530868877997210395[67] = 0.0;
   out_4530868877997210395[68] = 0.0;
   out_4530868877997210395[69] = 0.0;
   out_4530868877997210395[70] = 0.0;
   out_4530868877997210395[71] = 0.0;
   out_4530868877997210395[72] = 0.0;
   out_4530868877997210395[73] = 0.0;
   out_4530868877997210395[74] = 0.0;
   out_4530868877997210395[75] = 0.0;
   out_4530868877997210395[76] = 1.0;
   out_4530868877997210395[77] = 0.0;
   out_4530868877997210395[78] = 0.0;
   out_4530868877997210395[79] = 0.0;
   out_4530868877997210395[80] = 0.0;
   out_4530868877997210395[81] = 0.0;
   out_4530868877997210395[82] = 0.0;
   out_4530868877997210395[83] = 0.0;
   out_4530868877997210395[84] = 0.0;
   out_4530868877997210395[85] = 0.0;
   out_4530868877997210395[86] = 0.0;
   out_4530868877997210395[87] = 0.0;
   out_4530868877997210395[88] = 0.0;
   out_4530868877997210395[89] = 0.0;
   out_4530868877997210395[90] = 0.0;
   out_4530868877997210395[91] = 0.0;
   out_4530868877997210395[92] = 0.0;
   out_4530868877997210395[93] = 0.0;
   out_4530868877997210395[94] = 0.0;
   out_4530868877997210395[95] = 1.0;
   out_4530868877997210395[96] = 0.0;
   out_4530868877997210395[97] = 0.0;
   out_4530868877997210395[98] = 0.0;
   out_4530868877997210395[99] = 0.0;
   out_4530868877997210395[100] = 0.0;
   out_4530868877997210395[101] = 0.0;
   out_4530868877997210395[102] = 0.0;
   out_4530868877997210395[103] = 0.0;
   out_4530868877997210395[104] = 0.0;
   out_4530868877997210395[105] = 0.0;
   out_4530868877997210395[106] = 0.0;
   out_4530868877997210395[107] = 0.0;
   out_4530868877997210395[108] = 0.0;
   out_4530868877997210395[109] = 0.0;
   out_4530868877997210395[110] = 0.0;
   out_4530868877997210395[111] = 0.0;
   out_4530868877997210395[112] = 0.0;
   out_4530868877997210395[113] = 0.0;
   out_4530868877997210395[114] = 1.0;
   out_4530868877997210395[115] = 0.0;
   out_4530868877997210395[116] = 0.0;
   out_4530868877997210395[117] = 0.0;
   out_4530868877997210395[118] = 0.0;
   out_4530868877997210395[119] = 0.0;
   out_4530868877997210395[120] = 0.0;
   out_4530868877997210395[121] = 0.0;
   out_4530868877997210395[122] = 0.0;
   out_4530868877997210395[123] = 0.0;
   out_4530868877997210395[124] = 0.0;
   out_4530868877997210395[125] = 0.0;
   out_4530868877997210395[126] = 0.0;
   out_4530868877997210395[127] = 0.0;
   out_4530868877997210395[128] = 0.0;
   out_4530868877997210395[129] = 0.0;
   out_4530868877997210395[130] = 0.0;
   out_4530868877997210395[131] = 0.0;
   out_4530868877997210395[132] = 0.0;
   out_4530868877997210395[133] = 1.0;
   out_4530868877997210395[134] = 0.0;
   out_4530868877997210395[135] = 0.0;
   out_4530868877997210395[136] = 0.0;
   out_4530868877997210395[137] = 0.0;
   out_4530868877997210395[138] = 0.0;
   out_4530868877997210395[139] = 0.0;
   out_4530868877997210395[140] = 0.0;
   out_4530868877997210395[141] = 0.0;
   out_4530868877997210395[142] = 0.0;
   out_4530868877997210395[143] = 0.0;
   out_4530868877997210395[144] = 0.0;
   out_4530868877997210395[145] = 0.0;
   out_4530868877997210395[146] = 0.0;
   out_4530868877997210395[147] = 0.0;
   out_4530868877997210395[148] = 0.0;
   out_4530868877997210395[149] = 0.0;
   out_4530868877997210395[150] = 0.0;
   out_4530868877997210395[151] = 0.0;
   out_4530868877997210395[152] = 1.0;
   out_4530868877997210395[153] = 0.0;
   out_4530868877997210395[154] = 0.0;
   out_4530868877997210395[155] = 0.0;
   out_4530868877997210395[156] = 0.0;
   out_4530868877997210395[157] = 0.0;
   out_4530868877997210395[158] = 0.0;
   out_4530868877997210395[159] = 0.0;
   out_4530868877997210395[160] = 0.0;
   out_4530868877997210395[161] = 0.0;
   out_4530868877997210395[162] = 0.0;
   out_4530868877997210395[163] = 0.0;
   out_4530868877997210395[164] = 0.0;
   out_4530868877997210395[165] = 0.0;
   out_4530868877997210395[166] = 0.0;
   out_4530868877997210395[167] = 0.0;
   out_4530868877997210395[168] = 0.0;
   out_4530868877997210395[169] = 0.0;
   out_4530868877997210395[170] = 0.0;
   out_4530868877997210395[171] = 1.0;
   out_4530868877997210395[172] = 0.0;
   out_4530868877997210395[173] = 0.0;
   out_4530868877997210395[174] = 0.0;
   out_4530868877997210395[175] = 0.0;
   out_4530868877997210395[176] = 0.0;
   out_4530868877997210395[177] = 0.0;
   out_4530868877997210395[178] = 0.0;
   out_4530868877997210395[179] = 0.0;
   out_4530868877997210395[180] = 0.0;
   out_4530868877997210395[181] = 0.0;
   out_4530868877997210395[182] = 0.0;
   out_4530868877997210395[183] = 0.0;
   out_4530868877997210395[184] = 0.0;
   out_4530868877997210395[185] = 0.0;
   out_4530868877997210395[186] = 0.0;
   out_4530868877997210395[187] = 0.0;
   out_4530868877997210395[188] = 0.0;
   out_4530868877997210395[189] = 0.0;
   out_4530868877997210395[190] = 1.0;
   out_4530868877997210395[191] = 0.0;
   out_4530868877997210395[192] = 0.0;
   out_4530868877997210395[193] = 0.0;
   out_4530868877997210395[194] = 0.0;
   out_4530868877997210395[195] = 0.0;
   out_4530868877997210395[196] = 0.0;
   out_4530868877997210395[197] = 0.0;
   out_4530868877997210395[198] = 0.0;
   out_4530868877997210395[199] = 0.0;
   out_4530868877997210395[200] = 0.0;
   out_4530868877997210395[201] = 0.0;
   out_4530868877997210395[202] = 0.0;
   out_4530868877997210395[203] = 0.0;
   out_4530868877997210395[204] = 0.0;
   out_4530868877997210395[205] = 0.0;
   out_4530868877997210395[206] = 0.0;
   out_4530868877997210395[207] = 0.0;
   out_4530868877997210395[208] = 0.0;
   out_4530868877997210395[209] = 1.0;
   out_4530868877997210395[210] = 0.0;
   out_4530868877997210395[211] = 0.0;
   out_4530868877997210395[212] = 0.0;
   out_4530868877997210395[213] = 0.0;
   out_4530868877997210395[214] = 0.0;
   out_4530868877997210395[215] = 0.0;
   out_4530868877997210395[216] = 0.0;
   out_4530868877997210395[217] = 0.0;
   out_4530868877997210395[218] = 0.0;
   out_4530868877997210395[219] = 0.0;
   out_4530868877997210395[220] = 0.0;
   out_4530868877997210395[221] = 0.0;
   out_4530868877997210395[222] = 0.0;
   out_4530868877997210395[223] = 0.0;
   out_4530868877997210395[224] = 0.0;
   out_4530868877997210395[225] = 0.0;
   out_4530868877997210395[226] = 0.0;
   out_4530868877997210395[227] = 0.0;
   out_4530868877997210395[228] = 1.0;
   out_4530868877997210395[229] = 0.0;
   out_4530868877997210395[230] = 0.0;
   out_4530868877997210395[231] = 0.0;
   out_4530868877997210395[232] = 0.0;
   out_4530868877997210395[233] = 0.0;
   out_4530868877997210395[234] = 0.0;
   out_4530868877997210395[235] = 0.0;
   out_4530868877997210395[236] = 0.0;
   out_4530868877997210395[237] = 0.0;
   out_4530868877997210395[238] = 0.0;
   out_4530868877997210395[239] = 0.0;
   out_4530868877997210395[240] = 0.0;
   out_4530868877997210395[241] = 0.0;
   out_4530868877997210395[242] = 0.0;
   out_4530868877997210395[243] = 0.0;
   out_4530868877997210395[244] = 0.0;
   out_4530868877997210395[245] = 0.0;
   out_4530868877997210395[246] = 0.0;
   out_4530868877997210395[247] = 1.0;
   out_4530868877997210395[248] = 0.0;
   out_4530868877997210395[249] = 0.0;
   out_4530868877997210395[250] = 0.0;
   out_4530868877997210395[251] = 0.0;
   out_4530868877997210395[252] = 0.0;
   out_4530868877997210395[253] = 0.0;
   out_4530868877997210395[254] = 0.0;
   out_4530868877997210395[255] = 0.0;
   out_4530868877997210395[256] = 0.0;
   out_4530868877997210395[257] = 0.0;
   out_4530868877997210395[258] = 0.0;
   out_4530868877997210395[259] = 0.0;
   out_4530868877997210395[260] = 0.0;
   out_4530868877997210395[261] = 0.0;
   out_4530868877997210395[262] = 0.0;
   out_4530868877997210395[263] = 0.0;
   out_4530868877997210395[264] = 0.0;
   out_4530868877997210395[265] = 0.0;
   out_4530868877997210395[266] = 1.0;
   out_4530868877997210395[267] = 0.0;
   out_4530868877997210395[268] = 0.0;
   out_4530868877997210395[269] = 0.0;
   out_4530868877997210395[270] = 0.0;
   out_4530868877997210395[271] = 0.0;
   out_4530868877997210395[272] = 0.0;
   out_4530868877997210395[273] = 0.0;
   out_4530868877997210395[274] = 0.0;
   out_4530868877997210395[275] = 0.0;
   out_4530868877997210395[276] = 0.0;
   out_4530868877997210395[277] = 0.0;
   out_4530868877997210395[278] = 0.0;
   out_4530868877997210395[279] = 0.0;
   out_4530868877997210395[280] = 0.0;
   out_4530868877997210395[281] = 0.0;
   out_4530868877997210395[282] = 0.0;
   out_4530868877997210395[283] = 0.0;
   out_4530868877997210395[284] = 0.0;
   out_4530868877997210395[285] = 1.0;
   out_4530868877997210395[286] = 0.0;
   out_4530868877997210395[287] = 0.0;
   out_4530868877997210395[288] = 0.0;
   out_4530868877997210395[289] = 0.0;
   out_4530868877997210395[290] = 0.0;
   out_4530868877997210395[291] = 0.0;
   out_4530868877997210395[292] = 0.0;
   out_4530868877997210395[293] = 0.0;
   out_4530868877997210395[294] = 0.0;
   out_4530868877997210395[295] = 0.0;
   out_4530868877997210395[296] = 0.0;
   out_4530868877997210395[297] = 0.0;
   out_4530868877997210395[298] = 0.0;
   out_4530868877997210395[299] = 0.0;
   out_4530868877997210395[300] = 0.0;
   out_4530868877997210395[301] = 0.0;
   out_4530868877997210395[302] = 0.0;
   out_4530868877997210395[303] = 0.0;
   out_4530868877997210395[304] = 1.0;
   out_4530868877997210395[305] = 0.0;
   out_4530868877997210395[306] = 0.0;
   out_4530868877997210395[307] = 0.0;
   out_4530868877997210395[308] = 0.0;
   out_4530868877997210395[309] = 0.0;
   out_4530868877997210395[310] = 0.0;
   out_4530868877997210395[311] = 0.0;
   out_4530868877997210395[312] = 0.0;
   out_4530868877997210395[313] = 0.0;
   out_4530868877997210395[314] = 0.0;
   out_4530868877997210395[315] = 0.0;
   out_4530868877997210395[316] = 0.0;
   out_4530868877997210395[317] = 0.0;
   out_4530868877997210395[318] = 0.0;
   out_4530868877997210395[319] = 0.0;
   out_4530868877997210395[320] = 0.0;
   out_4530868877997210395[321] = 0.0;
   out_4530868877997210395[322] = 0.0;
   out_4530868877997210395[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_659554858487434793) {
   out_659554858487434793[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_659554858487434793[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_659554858487434793[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_659554858487434793[3] = dt*state[12] + state[3];
   out_659554858487434793[4] = dt*state[13] + state[4];
   out_659554858487434793[5] = dt*state[14] + state[5];
   out_659554858487434793[6] = state[6];
   out_659554858487434793[7] = state[7];
   out_659554858487434793[8] = state[8];
   out_659554858487434793[9] = state[9];
   out_659554858487434793[10] = state[10];
   out_659554858487434793[11] = state[11];
   out_659554858487434793[12] = state[12];
   out_659554858487434793[13] = state[13];
   out_659554858487434793[14] = state[14];
   out_659554858487434793[15] = state[15];
   out_659554858487434793[16] = state[16];
   out_659554858487434793[17] = state[17];
}
void F_fun(double *state, double dt, double *out_8122516567546015023) {
   out_8122516567546015023[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8122516567546015023[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8122516567546015023[2] = 0;
   out_8122516567546015023[3] = 0;
   out_8122516567546015023[4] = 0;
   out_8122516567546015023[5] = 0;
   out_8122516567546015023[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8122516567546015023[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8122516567546015023[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_8122516567546015023[9] = 0;
   out_8122516567546015023[10] = 0;
   out_8122516567546015023[11] = 0;
   out_8122516567546015023[12] = 0;
   out_8122516567546015023[13] = 0;
   out_8122516567546015023[14] = 0;
   out_8122516567546015023[15] = 0;
   out_8122516567546015023[16] = 0;
   out_8122516567546015023[17] = 0;
   out_8122516567546015023[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8122516567546015023[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8122516567546015023[20] = 0;
   out_8122516567546015023[21] = 0;
   out_8122516567546015023[22] = 0;
   out_8122516567546015023[23] = 0;
   out_8122516567546015023[24] = 0;
   out_8122516567546015023[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8122516567546015023[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_8122516567546015023[27] = 0;
   out_8122516567546015023[28] = 0;
   out_8122516567546015023[29] = 0;
   out_8122516567546015023[30] = 0;
   out_8122516567546015023[31] = 0;
   out_8122516567546015023[32] = 0;
   out_8122516567546015023[33] = 0;
   out_8122516567546015023[34] = 0;
   out_8122516567546015023[35] = 0;
   out_8122516567546015023[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8122516567546015023[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8122516567546015023[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8122516567546015023[39] = 0;
   out_8122516567546015023[40] = 0;
   out_8122516567546015023[41] = 0;
   out_8122516567546015023[42] = 0;
   out_8122516567546015023[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8122516567546015023[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_8122516567546015023[45] = 0;
   out_8122516567546015023[46] = 0;
   out_8122516567546015023[47] = 0;
   out_8122516567546015023[48] = 0;
   out_8122516567546015023[49] = 0;
   out_8122516567546015023[50] = 0;
   out_8122516567546015023[51] = 0;
   out_8122516567546015023[52] = 0;
   out_8122516567546015023[53] = 0;
   out_8122516567546015023[54] = 0;
   out_8122516567546015023[55] = 0;
   out_8122516567546015023[56] = 0;
   out_8122516567546015023[57] = 1;
   out_8122516567546015023[58] = 0;
   out_8122516567546015023[59] = 0;
   out_8122516567546015023[60] = 0;
   out_8122516567546015023[61] = 0;
   out_8122516567546015023[62] = 0;
   out_8122516567546015023[63] = 0;
   out_8122516567546015023[64] = 0;
   out_8122516567546015023[65] = 0;
   out_8122516567546015023[66] = dt;
   out_8122516567546015023[67] = 0;
   out_8122516567546015023[68] = 0;
   out_8122516567546015023[69] = 0;
   out_8122516567546015023[70] = 0;
   out_8122516567546015023[71] = 0;
   out_8122516567546015023[72] = 0;
   out_8122516567546015023[73] = 0;
   out_8122516567546015023[74] = 0;
   out_8122516567546015023[75] = 0;
   out_8122516567546015023[76] = 1;
   out_8122516567546015023[77] = 0;
   out_8122516567546015023[78] = 0;
   out_8122516567546015023[79] = 0;
   out_8122516567546015023[80] = 0;
   out_8122516567546015023[81] = 0;
   out_8122516567546015023[82] = 0;
   out_8122516567546015023[83] = 0;
   out_8122516567546015023[84] = 0;
   out_8122516567546015023[85] = dt;
   out_8122516567546015023[86] = 0;
   out_8122516567546015023[87] = 0;
   out_8122516567546015023[88] = 0;
   out_8122516567546015023[89] = 0;
   out_8122516567546015023[90] = 0;
   out_8122516567546015023[91] = 0;
   out_8122516567546015023[92] = 0;
   out_8122516567546015023[93] = 0;
   out_8122516567546015023[94] = 0;
   out_8122516567546015023[95] = 1;
   out_8122516567546015023[96] = 0;
   out_8122516567546015023[97] = 0;
   out_8122516567546015023[98] = 0;
   out_8122516567546015023[99] = 0;
   out_8122516567546015023[100] = 0;
   out_8122516567546015023[101] = 0;
   out_8122516567546015023[102] = 0;
   out_8122516567546015023[103] = 0;
   out_8122516567546015023[104] = dt;
   out_8122516567546015023[105] = 0;
   out_8122516567546015023[106] = 0;
   out_8122516567546015023[107] = 0;
   out_8122516567546015023[108] = 0;
   out_8122516567546015023[109] = 0;
   out_8122516567546015023[110] = 0;
   out_8122516567546015023[111] = 0;
   out_8122516567546015023[112] = 0;
   out_8122516567546015023[113] = 0;
   out_8122516567546015023[114] = 1;
   out_8122516567546015023[115] = 0;
   out_8122516567546015023[116] = 0;
   out_8122516567546015023[117] = 0;
   out_8122516567546015023[118] = 0;
   out_8122516567546015023[119] = 0;
   out_8122516567546015023[120] = 0;
   out_8122516567546015023[121] = 0;
   out_8122516567546015023[122] = 0;
   out_8122516567546015023[123] = 0;
   out_8122516567546015023[124] = 0;
   out_8122516567546015023[125] = 0;
   out_8122516567546015023[126] = 0;
   out_8122516567546015023[127] = 0;
   out_8122516567546015023[128] = 0;
   out_8122516567546015023[129] = 0;
   out_8122516567546015023[130] = 0;
   out_8122516567546015023[131] = 0;
   out_8122516567546015023[132] = 0;
   out_8122516567546015023[133] = 1;
   out_8122516567546015023[134] = 0;
   out_8122516567546015023[135] = 0;
   out_8122516567546015023[136] = 0;
   out_8122516567546015023[137] = 0;
   out_8122516567546015023[138] = 0;
   out_8122516567546015023[139] = 0;
   out_8122516567546015023[140] = 0;
   out_8122516567546015023[141] = 0;
   out_8122516567546015023[142] = 0;
   out_8122516567546015023[143] = 0;
   out_8122516567546015023[144] = 0;
   out_8122516567546015023[145] = 0;
   out_8122516567546015023[146] = 0;
   out_8122516567546015023[147] = 0;
   out_8122516567546015023[148] = 0;
   out_8122516567546015023[149] = 0;
   out_8122516567546015023[150] = 0;
   out_8122516567546015023[151] = 0;
   out_8122516567546015023[152] = 1;
   out_8122516567546015023[153] = 0;
   out_8122516567546015023[154] = 0;
   out_8122516567546015023[155] = 0;
   out_8122516567546015023[156] = 0;
   out_8122516567546015023[157] = 0;
   out_8122516567546015023[158] = 0;
   out_8122516567546015023[159] = 0;
   out_8122516567546015023[160] = 0;
   out_8122516567546015023[161] = 0;
   out_8122516567546015023[162] = 0;
   out_8122516567546015023[163] = 0;
   out_8122516567546015023[164] = 0;
   out_8122516567546015023[165] = 0;
   out_8122516567546015023[166] = 0;
   out_8122516567546015023[167] = 0;
   out_8122516567546015023[168] = 0;
   out_8122516567546015023[169] = 0;
   out_8122516567546015023[170] = 0;
   out_8122516567546015023[171] = 1;
   out_8122516567546015023[172] = 0;
   out_8122516567546015023[173] = 0;
   out_8122516567546015023[174] = 0;
   out_8122516567546015023[175] = 0;
   out_8122516567546015023[176] = 0;
   out_8122516567546015023[177] = 0;
   out_8122516567546015023[178] = 0;
   out_8122516567546015023[179] = 0;
   out_8122516567546015023[180] = 0;
   out_8122516567546015023[181] = 0;
   out_8122516567546015023[182] = 0;
   out_8122516567546015023[183] = 0;
   out_8122516567546015023[184] = 0;
   out_8122516567546015023[185] = 0;
   out_8122516567546015023[186] = 0;
   out_8122516567546015023[187] = 0;
   out_8122516567546015023[188] = 0;
   out_8122516567546015023[189] = 0;
   out_8122516567546015023[190] = 1;
   out_8122516567546015023[191] = 0;
   out_8122516567546015023[192] = 0;
   out_8122516567546015023[193] = 0;
   out_8122516567546015023[194] = 0;
   out_8122516567546015023[195] = 0;
   out_8122516567546015023[196] = 0;
   out_8122516567546015023[197] = 0;
   out_8122516567546015023[198] = 0;
   out_8122516567546015023[199] = 0;
   out_8122516567546015023[200] = 0;
   out_8122516567546015023[201] = 0;
   out_8122516567546015023[202] = 0;
   out_8122516567546015023[203] = 0;
   out_8122516567546015023[204] = 0;
   out_8122516567546015023[205] = 0;
   out_8122516567546015023[206] = 0;
   out_8122516567546015023[207] = 0;
   out_8122516567546015023[208] = 0;
   out_8122516567546015023[209] = 1;
   out_8122516567546015023[210] = 0;
   out_8122516567546015023[211] = 0;
   out_8122516567546015023[212] = 0;
   out_8122516567546015023[213] = 0;
   out_8122516567546015023[214] = 0;
   out_8122516567546015023[215] = 0;
   out_8122516567546015023[216] = 0;
   out_8122516567546015023[217] = 0;
   out_8122516567546015023[218] = 0;
   out_8122516567546015023[219] = 0;
   out_8122516567546015023[220] = 0;
   out_8122516567546015023[221] = 0;
   out_8122516567546015023[222] = 0;
   out_8122516567546015023[223] = 0;
   out_8122516567546015023[224] = 0;
   out_8122516567546015023[225] = 0;
   out_8122516567546015023[226] = 0;
   out_8122516567546015023[227] = 0;
   out_8122516567546015023[228] = 1;
   out_8122516567546015023[229] = 0;
   out_8122516567546015023[230] = 0;
   out_8122516567546015023[231] = 0;
   out_8122516567546015023[232] = 0;
   out_8122516567546015023[233] = 0;
   out_8122516567546015023[234] = 0;
   out_8122516567546015023[235] = 0;
   out_8122516567546015023[236] = 0;
   out_8122516567546015023[237] = 0;
   out_8122516567546015023[238] = 0;
   out_8122516567546015023[239] = 0;
   out_8122516567546015023[240] = 0;
   out_8122516567546015023[241] = 0;
   out_8122516567546015023[242] = 0;
   out_8122516567546015023[243] = 0;
   out_8122516567546015023[244] = 0;
   out_8122516567546015023[245] = 0;
   out_8122516567546015023[246] = 0;
   out_8122516567546015023[247] = 1;
   out_8122516567546015023[248] = 0;
   out_8122516567546015023[249] = 0;
   out_8122516567546015023[250] = 0;
   out_8122516567546015023[251] = 0;
   out_8122516567546015023[252] = 0;
   out_8122516567546015023[253] = 0;
   out_8122516567546015023[254] = 0;
   out_8122516567546015023[255] = 0;
   out_8122516567546015023[256] = 0;
   out_8122516567546015023[257] = 0;
   out_8122516567546015023[258] = 0;
   out_8122516567546015023[259] = 0;
   out_8122516567546015023[260] = 0;
   out_8122516567546015023[261] = 0;
   out_8122516567546015023[262] = 0;
   out_8122516567546015023[263] = 0;
   out_8122516567546015023[264] = 0;
   out_8122516567546015023[265] = 0;
   out_8122516567546015023[266] = 1;
   out_8122516567546015023[267] = 0;
   out_8122516567546015023[268] = 0;
   out_8122516567546015023[269] = 0;
   out_8122516567546015023[270] = 0;
   out_8122516567546015023[271] = 0;
   out_8122516567546015023[272] = 0;
   out_8122516567546015023[273] = 0;
   out_8122516567546015023[274] = 0;
   out_8122516567546015023[275] = 0;
   out_8122516567546015023[276] = 0;
   out_8122516567546015023[277] = 0;
   out_8122516567546015023[278] = 0;
   out_8122516567546015023[279] = 0;
   out_8122516567546015023[280] = 0;
   out_8122516567546015023[281] = 0;
   out_8122516567546015023[282] = 0;
   out_8122516567546015023[283] = 0;
   out_8122516567546015023[284] = 0;
   out_8122516567546015023[285] = 1;
   out_8122516567546015023[286] = 0;
   out_8122516567546015023[287] = 0;
   out_8122516567546015023[288] = 0;
   out_8122516567546015023[289] = 0;
   out_8122516567546015023[290] = 0;
   out_8122516567546015023[291] = 0;
   out_8122516567546015023[292] = 0;
   out_8122516567546015023[293] = 0;
   out_8122516567546015023[294] = 0;
   out_8122516567546015023[295] = 0;
   out_8122516567546015023[296] = 0;
   out_8122516567546015023[297] = 0;
   out_8122516567546015023[298] = 0;
   out_8122516567546015023[299] = 0;
   out_8122516567546015023[300] = 0;
   out_8122516567546015023[301] = 0;
   out_8122516567546015023[302] = 0;
   out_8122516567546015023[303] = 0;
   out_8122516567546015023[304] = 1;
   out_8122516567546015023[305] = 0;
   out_8122516567546015023[306] = 0;
   out_8122516567546015023[307] = 0;
   out_8122516567546015023[308] = 0;
   out_8122516567546015023[309] = 0;
   out_8122516567546015023[310] = 0;
   out_8122516567546015023[311] = 0;
   out_8122516567546015023[312] = 0;
   out_8122516567546015023[313] = 0;
   out_8122516567546015023[314] = 0;
   out_8122516567546015023[315] = 0;
   out_8122516567546015023[316] = 0;
   out_8122516567546015023[317] = 0;
   out_8122516567546015023[318] = 0;
   out_8122516567546015023[319] = 0;
   out_8122516567546015023[320] = 0;
   out_8122516567546015023[321] = 0;
   out_8122516567546015023[322] = 0;
   out_8122516567546015023[323] = 1;
}
void h_4(double *state, double *unused, double *out_8968392969190010627) {
   out_8968392969190010627[0] = state[6] + state[9];
   out_8968392969190010627[1] = state[7] + state[10];
   out_8968392969190010627[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_3406733573803791520) {
   out_3406733573803791520[0] = 0;
   out_3406733573803791520[1] = 0;
   out_3406733573803791520[2] = 0;
   out_3406733573803791520[3] = 0;
   out_3406733573803791520[4] = 0;
   out_3406733573803791520[5] = 0;
   out_3406733573803791520[6] = 1;
   out_3406733573803791520[7] = 0;
   out_3406733573803791520[8] = 0;
   out_3406733573803791520[9] = 1;
   out_3406733573803791520[10] = 0;
   out_3406733573803791520[11] = 0;
   out_3406733573803791520[12] = 0;
   out_3406733573803791520[13] = 0;
   out_3406733573803791520[14] = 0;
   out_3406733573803791520[15] = 0;
   out_3406733573803791520[16] = 0;
   out_3406733573803791520[17] = 0;
   out_3406733573803791520[18] = 0;
   out_3406733573803791520[19] = 0;
   out_3406733573803791520[20] = 0;
   out_3406733573803791520[21] = 0;
   out_3406733573803791520[22] = 0;
   out_3406733573803791520[23] = 0;
   out_3406733573803791520[24] = 0;
   out_3406733573803791520[25] = 1;
   out_3406733573803791520[26] = 0;
   out_3406733573803791520[27] = 0;
   out_3406733573803791520[28] = 1;
   out_3406733573803791520[29] = 0;
   out_3406733573803791520[30] = 0;
   out_3406733573803791520[31] = 0;
   out_3406733573803791520[32] = 0;
   out_3406733573803791520[33] = 0;
   out_3406733573803791520[34] = 0;
   out_3406733573803791520[35] = 0;
   out_3406733573803791520[36] = 0;
   out_3406733573803791520[37] = 0;
   out_3406733573803791520[38] = 0;
   out_3406733573803791520[39] = 0;
   out_3406733573803791520[40] = 0;
   out_3406733573803791520[41] = 0;
   out_3406733573803791520[42] = 0;
   out_3406733573803791520[43] = 0;
   out_3406733573803791520[44] = 1;
   out_3406733573803791520[45] = 0;
   out_3406733573803791520[46] = 0;
   out_3406733573803791520[47] = 1;
   out_3406733573803791520[48] = 0;
   out_3406733573803791520[49] = 0;
   out_3406733573803791520[50] = 0;
   out_3406733573803791520[51] = 0;
   out_3406733573803791520[52] = 0;
   out_3406733573803791520[53] = 0;
}
void h_10(double *state, double *unused, double *out_4778739924469370119) {
   out_4778739924469370119[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_4778739924469370119[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_4778739924469370119[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_4773808119150424256) {
   out_4773808119150424256[0] = 0;
   out_4773808119150424256[1] = 9.8100000000000005*cos(state[1]);
   out_4773808119150424256[2] = 0;
   out_4773808119150424256[3] = 0;
   out_4773808119150424256[4] = -state[8];
   out_4773808119150424256[5] = state[7];
   out_4773808119150424256[6] = 0;
   out_4773808119150424256[7] = state[5];
   out_4773808119150424256[8] = -state[4];
   out_4773808119150424256[9] = 0;
   out_4773808119150424256[10] = 0;
   out_4773808119150424256[11] = 0;
   out_4773808119150424256[12] = 1;
   out_4773808119150424256[13] = 0;
   out_4773808119150424256[14] = 0;
   out_4773808119150424256[15] = 1;
   out_4773808119150424256[16] = 0;
   out_4773808119150424256[17] = 0;
   out_4773808119150424256[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_4773808119150424256[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_4773808119150424256[20] = 0;
   out_4773808119150424256[21] = state[8];
   out_4773808119150424256[22] = 0;
   out_4773808119150424256[23] = -state[6];
   out_4773808119150424256[24] = -state[5];
   out_4773808119150424256[25] = 0;
   out_4773808119150424256[26] = state[3];
   out_4773808119150424256[27] = 0;
   out_4773808119150424256[28] = 0;
   out_4773808119150424256[29] = 0;
   out_4773808119150424256[30] = 0;
   out_4773808119150424256[31] = 1;
   out_4773808119150424256[32] = 0;
   out_4773808119150424256[33] = 0;
   out_4773808119150424256[34] = 1;
   out_4773808119150424256[35] = 0;
   out_4773808119150424256[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_4773808119150424256[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_4773808119150424256[38] = 0;
   out_4773808119150424256[39] = -state[7];
   out_4773808119150424256[40] = state[6];
   out_4773808119150424256[41] = 0;
   out_4773808119150424256[42] = state[4];
   out_4773808119150424256[43] = -state[3];
   out_4773808119150424256[44] = 0;
   out_4773808119150424256[45] = 0;
   out_4773808119150424256[46] = 0;
   out_4773808119150424256[47] = 0;
   out_4773808119150424256[48] = 0;
   out_4773808119150424256[49] = 0;
   out_4773808119150424256[50] = 1;
   out_4773808119150424256[51] = 0;
   out_4773808119150424256[52] = 0;
   out_4773808119150424256[53] = 1;
}
void h_13(double *state, double *unused, double *out_8774561321168379953) {
   out_8774561321168379953[0] = state[3];
   out_8774561321168379953[1] = state[4];
   out_8774561321168379953[2] = state[5];
}
void H_13(double *state, double *unused, double *out_194459748471458719) {
   out_194459748471458719[0] = 0;
   out_194459748471458719[1] = 0;
   out_194459748471458719[2] = 0;
   out_194459748471458719[3] = 1;
   out_194459748471458719[4] = 0;
   out_194459748471458719[5] = 0;
   out_194459748471458719[6] = 0;
   out_194459748471458719[7] = 0;
   out_194459748471458719[8] = 0;
   out_194459748471458719[9] = 0;
   out_194459748471458719[10] = 0;
   out_194459748471458719[11] = 0;
   out_194459748471458719[12] = 0;
   out_194459748471458719[13] = 0;
   out_194459748471458719[14] = 0;
   out_194459748471458719[15] = 0;
   out_194459748471458719[16] = 0;
   out_194459748471458719[17] = 0;
   out_194459748471458719[18] = 0;
   out_194459748471458719[19] = 0;
   out_194459748471458719[20] = 0;
   out_194459748471458719[21] = 0;
   out_194459748471458719[22] = 1;
   out_194459748471458719[23] = 0;
   out_194459748471458719[24] = 0;
   out_194459748471458719[25] = 0;
   out_194459748471458719[26] = 0;
   out_194459748471458719[27] = 0;
   out_194459748471458719[28] = 0;
   out_194459748471458719[29] = 0;
   out_194459748471458719[30] = 0;
   out_194459748471458719[31] = 0;
   out_194459748471458719[32] = 0;
   out_194459748471458719[33] = 0;
   out_194459748471458719[34] = 0;
   out_194459748471458719[35] = 0;
   out_194459748471458719[36] = 0;
   out_194459748471458719[37] = 0;
   out_194459748471458719[38] = 0;
   out_194459748471458719[39] = 0;
   out_194459748471458719[40] = 0;
   out_194459748471458719[41] = 1;
   out_194459748471458719[42] = 0;
   out_194459748471458719[43] = 0;
   out_194459748471458719[44] = 0;
   out_194459748471458719[45] = 0;
   out_194459748471458719[46] = 0;
   out_194459748471458719[47] = 0;
   out_194459748471458719[48] = 0;
   out_194459748471458719[49] = 0;
   out_194459748471458719[50] = 0;
   out_194459748471458719[51] = 0;
   out_194459748471458719[52] = 0;
   out_194459748471458719[53] = 0;
}
void h_14(double *state, double *unused, double *out_4087694789546319597) {
   out_4087694789546319597[0] = state[6];
   out_4087694789546319597[1] = state[7];
   out_4087694789546319597[2] = state[8];
}
void H_14(double *state, double *unused, double *out_3841850100448675119) {
   out_3841850100448675119[0] = 0;
   out_3841850100448675119[1] = 0;
   out_3841850100448675119[2] = 0;
   out_3841850100448675119[3] = 0;
   out_3841850100448675119[4] = 0;
   out_3841850100448675119[5] = 0;
   out_3841850100448675119[6] = 1;
   out_3841850100448675119[7] = 0;
   out_3841850100448675119[8] = 0;
   out_3841850100448675119[9] = 0;
   out_3841850100448675119[10] = 0;
   out_3841850100448675119[11] = 0;
   out_3841850100448675119[12] = 0;
   out_3841850100448675119[13] = 0;
   out_3841850100448675119[14] = 0;
   out_3841850100448675119[15] = 0;
   out_3841850100448675119[16] = 0;
   out_3841850100448675119[17] = 0;
   out_3841850100448675119[18] = 0;
   out_3841850100448675119[19] = 0;
   out_3841850100448675119[20] = 0;
   out_3841850100448675119[21] = 0;
   out_3841850100448675119[22] = 0;
   out_3841850100448675119[23] = 0;
   out_3841850100448675119[24] = 0;
   out_3841850100448675119[25] = 1;
   out_3841850100448675119[26] = 0;
   out_3841850100448675119[27] = 0;
   out_3841850100448675119[28] = 0;
   out_3841850100448675119[29] = 0;
   out_3841850100448675119[30] = 0;
   out_3841850100448675119[31] = 0;
   out_3841850100448675119[32] = 0;
   out_3841850100448675119[33] = 0;
   out_3841850100448675119[34] = 0;
   out_3841850100448675119[35] = 0;
   out_3841850100448675119[36] = 0;
   out_3841850100448675119[37] = 0;
   out_3841850100448675119[38] = 0;
   out_3841850100448675119[39] = 0;
   out_3841850100448675119[40] = 0;
   out_3841850100448675119[41] = 0;
   out_3841850100448675119[42] = 0;
   out_3841850100448675119[43] = 0;
   out_3841850100448675119[44] = 1;
   out_3841850100448675119[45] = 0;
   out_3841850100448675119[46] = 0;
   out_3841850100448675119[47] = 0;
   out_3841850100448675119[48] = 0;
   out_3841850100448675119[49] = 0;
   out_3841850100448675119[50] = 0;
   out_3841850100448675119[51] = 0;
   out_3841850100448675119[52] = 0;
   out_3841850100448675119[53] = 0;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_6160433194432564726) {
  err_fun(nom_x, delta_x, out_6160433194432564726);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_2084276865667981673) {
  inv_err_fun(nom_x, true_x, out_2084276865667981673);
}
void pose_H_mod_fun(double *state, double *out_4530868877997210395) {
  H_mod_fun(state, out_4530868877997210395);
}
void pose_f_fun(double *state, double dt, double *out_659554858487434793) {
  f_fun(state,  dt, out_659554858487434793);
}
void pose_F_fun(double *state, double dt, double *out_8122516567546015023) {
  F_fun(state,  dt, out_8122516567546015023);
}
void pose_h_4(double *state, double *unused, double *out_8968392969190010627) {
  h_4(state, unused, out_8968392969190010627);
}
void pose_H_4(double *state, double *unused, double *out_3406733573803791520) {
  H_4(state, unused, out_3406733573803791520);
}
void pose_h_10(double *state, double *unused, double *out_4778739924469370119) {
  h_10(state, unused, out_4778739924469370119);
}
void pose_H_10(double *state, double *unused, double *out_4773808119150424256) {
  H_10(state, unused, out_4773808119150424256);
}
void pose_h_13(double *state, double *unused, double *out_8774561321168379953) {
  h_13(state, unused, out_8774561321168379953);
}
void pose_H_13(double *state, double *unused, double *out_194459748471458719) {
  H_13(state, unused, out_194459748471458719);
}
void pose_h_14(double *state, double *unused, double *out_4087694789546319597) {
  h_14(state, unused, out_4087694789546319597);
}
void pose_H_14(double *state, double *unused, double *out_3841850100448675119) {
  H_14(state, unused, out_3841850100448675119);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
