/*
 * fdtd_3d_ant.c -- Full-Wave 3D Non-Uniform Yee-Grid FDTD Maxwell Curl Solver
 *                  with 8-Cell CPML Absorbing Boundaries, Exact Spectral
 *                  Dielectric + ENIG Conductor Loss Integration, and Frequency-
 *                  Resolved Radiation Efficiency for ISAC_868_KiCad9 Rev E.5
 *                  (BLK-03, HIGH-03, MED-01).
 *
 * Solves time-dependent 3D Maxwell curl equations directly from first principles:
 *   curl(E) = -mu_0 * dH/dt
 *   curl(H) = eps * dE/dt + sigma * E + J_src
 *
 * Finite conductor loss (IPC-4552 ENIG NiP/Au over 1 oz Cu) is modeled via
 * unconditionally stable exponential time-stepping sheet conductance
 * (sig_sheet = 1 / (R_sheet * dz_h)) on tangential conductor edges.
 *
 * Per-frequency radiation efficiency eta_rad(f) = (P_acc(f) - P_loss(f)) / P_acc(f)
 * is evaluated directly from Poynting's theorem on the staggered Yee grid by
 * integrating the complex DFT electric-field phasors E(r, f) across every lossy
 * dielectric and finite-conductivity ENIG edge:
 *   P_loss(f) = 0.5 * sum_e G_e * |E_e(f)|^2 >= 0
 * avoiding reactive near-field cancellation errors near compact enclosures.
 *
 * Compiled via:
 *   gcc -O3 -march=native -fopenmp -shared -fPIC -Wall -Wextra -Werror \
 *       rf/fdtd_3d_ant.c -o rf/libfdtd_3d_ant.so -lm
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _OPENMP
#include <omp.h>
#endif

#define MU0  (1.25663706212e-6)
#define EPS0 (8.8541878128e-12)
#define C0   (299792458.0)
#define PI   (3.14159265358979323846)

#define MAX_LOSS_ANCHORS 25
#define LOSS_DECIM       16

typedef struct {
    uint32_t idx;
    uint8_t  axis;   /* 0 = Ex, 1 = Ey, 2 = Ez */
    float    g_vol;  /* sigma_eff * dV [S * m] so 0.5 * g_vol * |E(f)|^2 = P_loss(f) */
} loss_edge_t;

int fdtd_solve_port(
    int nx, int ny, int nz,
    const double *x, const double *y, const double *z,
    const float *cell_eps_r,
    const float *cell_sigma,
    const uint8_t *pec_ex,
    const uint8_t *pec_ey,
    const uint8_t *pec_ez,
    double r_sheet_ohm,
    int port_axis,
    int p_i, int p_j0, int p_j1, int p_k0, int p_k1,
    double r_src_ohm,
    int n_steps,
    int npml,
    double f0_pulse,
    double f_span_pulse,
    int n_freqs,
    const double *freqs_hz,
    double *out_v_re,
    double *out_v_im,
    double *out_i_re,
    double *out_i_im,
    double *out_rad_eff
) {
    if (nx < 20 || ny < 20 || nz < 20 || p_j1 <= p_j0 || n_freqs <= 0) {
        return -1;
    }

    double *dx = (double *)calloc((size_t)nx, sizeof(double));
    double *dy = (double *)calloc((size_t)ny, sizeof(double));
    double *dz = (double *)calloc((size_t)nz, sizeof(double));
    double *dxh = (double *)calloc((size_t)(nx + 1), sizeof(double));
    double *dyh = (double *)calloc((size_t)(ny + 1), sizeof(double));
    double *dzh = (double *)calloc((size_t)(nz + 1), sizeof(double));

    double dmin_inv2 = 0.0;
    for (int i = 0; i < nx; i++) dx[i] = x[i + 1] - x[i];
    for (int j = 0; j < ny; j++) dy[j] = y[j + 1] - y[j];
    for (int k = 0; k < nz; k++) dz[k] = z[k + 1] - z[k];

    for (int k = 0; k < nz; k++) {
        for (int j = 0; j < ny; j++) {
            for (int i = 0; i < nx; i++) {
                double inv2 = 1.0 / (dx[i] * dx[i]) + 1.0 / (dy[j] * dy[j]) + 1.0 / (dz[k] * dz[k]);
                if (inv2 > dmin_inv2) dmin_inv2 = inv2;
            }
        }
    }

    dxh[0] = dx[0];
    for (int i = 1; i < nx; i++) dxh[i] = 0.5 * (dx[i - 1] + dx[i]);
    dxh[nx] = dx[nx - 1];

    dyh[0] = dy[0];
    for (int j = 1; j < ny; j++) dyh[j] = 0.5 * (dy[j - 1] + dy[j]);
    dyh[ny] = dy[ny - 1];

    dzh[0] = dz[0];
    for (int k = 1; k < nz; k++) dzh[k] = 0.5 * (dz[k - 1] + dz[k]);
    dzh[nz] = dz[nz - 1];

    const double dt = 0.90 / (C0 * sqrt(dmin_inv2));

    const size_t n_ex = (size_t)(nz + 1) * (size_t)(ny + 1) * (size_t)nx;
    const size_t n_ey = (size_t)(nz + 1) * (size_t)ny * (size_t)(nx + 1);
    const size_t n_ez = (size_t)nz * (size_t)(ny + 1) * (size_t)(nx + 1);

    const size_t n_hx = (size_t)nz * (size_t)ny * (size_t)(nx + 1);
    const size_t n_hy = (size_t)nz * (size_t)(ny + 1) * (size_t)nx;
    const size_t n_hz = (size_t)(nz + 1) * (size_t)ny * (size_t)nx;

    float *Ex = (float *)calloc(n_ex, sizeof(float));
    float *Ey = (float *)calloc(n_ey, sizeof(float));
    float *Ez = (float *)calloc(n_ez, sizeof(float));
    float *Hx = (float *)calloc(n_hx, sizeof(float));
    float *Hy = (float *)calloc(n_hy, sizeof(float));
    float *Hz = (float *)calloc(n_hz, sizeof(float));

    float *ca_ex = (float *)calloc(n_ex, sizeof(float));
    float *cb_ex = (float *)calloc(n_ex, sizeof(float));
    float *ca_ey = (float *)calloc(n_ey, sizeof(float));
    float *cb_ey = (float *)calloc(n_ey, sizeof(float));
    float *ca_ez = (float *)calloc(n_ez, sizeof(float));
    float *cb_ez = (float *)calloc(n_ez, sizeof(float));

    if (!Ex || !Ey || !Ez || !Hx || !Hy || !Hz ||
        !ca_ex || !cb_ex || !ca_ey || !cb_ey || !ca_ez || !cb_ez) {
        return -2;
    }

    #define CELL_IDX(k, j, i) (((size_t)(k) * (size_t)ny + (size_t)(j)) * (size_t)nx + (size_t)(i))
    #define EX_IDX(k, j, i)   (((size_t)(k) * (size_t)(ny + 1) + (size_t)(j)) * (size_t)nx + (size_t)(i))
    #define EY_IDX(k, j, i)   (((size_t)(k) * (size_t)ny + (size_t)(j)) * (size_t)(nx + 1) + (size_t)(i))
    #define EZ_IDX(k, j, i)   (((size_t)(k) * (size_t)(ny + 1) + (size_t)(j)) * (size_t)(nx + 1) + (size_t)(i))
    #define HX_IDX(k, j, i)   (((size_t)(k) * (size_t)ny + (size_t)(j)) * (size_t)(nx + 1) + (size_t)(i))
    #define HY_IDX(k, j, i)   (((size_t)(k) * (size_t)(ny + 1) + (size_t)(j)) * (size_t)nx + (size_t)(i))
    #define HZ_IDX(k, j, i)   (((size_t)(k) * (size_t)ny + (size_t)(j)) * (size_t)nx + (size_t)(i))

    double w_dual_y = 0.0;
    for (int j = p_j0; j < p_j1; j++) {
        w_dual_y += dyh[j];
    }
    double h_port_z = (port_axis == 2) ? (z[p_k1] - z[p_k0]) : dzh[p_k0];
    double l_port_x = dx[p_i];

    size_t loss_cap = 131072U;
    size_t n_loss = 0;
    loss_edge_t *loss_edges = (loss_edge_t *)malloc(loss_cap * sizeof(loss_edge_t));
    if (!loss_edges) return -3;

    #define PUSH_LOSS_EDGE(e_idx, e_axis, g_val) do { \
        if ((g_val) > 1e-16) { \
            if (n_loss >= loss_cap) { \
                loss_cap *= 2U; \
                loss_edge_t * grown = (loss_edge_t *)realloc(loss_edges, loss_cap * sizeof(loss_edge_t)); \
                if (!grown) return -3; \
                loss_edges = grown; \
            } \
            loss_edges[n_loss].idx = (uint32_t)(e_idx); \
            loss_edges[n_loss].axis = (uint8_t)(e_axis); \
            loss_edges[n_loss].g_vol = (float)(g_val); \
            n_loss++; \
        } \
    } while (0)

    /* Precompute dual-volume area-weighted material update coefficients on E edges */
    for (int k = 1; k < nz; k++) {
        for (int j = 1; j < ny; j++) {
            for (int i = 0; i < nx; i++) {
                size_t idx = EX_IDX(k, j, i);
                int in_box = (i >= npml && i < nx - npml &&
                              j >= npml && j <= ny - npml &&
                              k >= npml && k <= nz - npml);
                int is_port = (port_axis == 0 && i == p_i && j >= p_j0 && j < p_j1 && k == p_k0);
                double dvol = dx[i] * dyh[j] * dzh[k];
                if (pec_ex[idx] && !is_port) {
                    if (r_sheet_ohm > 1e-9) {
                        double wsum = 0.0, ep_sum = 0.0;
                        for (int dk = -1; dk <= 0; dk++) {
                            for (int dj = -1; dj <= 0; dj++) {
                                double w = dz[k + dk] * dy[j + dj];
                                wsum += w;
                                ep_sum += w * (double)cell_eps_r[CELL_IDX(k + dk, j + dj, i)];
                            }
                        }
                        double eps = EPS0 * (ep_sum / wsum);
                        double sig_sheet = 1.0 / (r_sheet_ohm * dzh[k]);
                        double expo = exp(-sig_sheet * dt / eps);
                        ca_ex[idx] = (float)expo;
                        cb_ex[idx] = (float)((1.0 - expo) / sig_sheet);
                        if (in_box) PUSH_LOSS_EDGE(idx, 0, sig_sheet * dvol);
                    } else {
                        ca_ex[idx] = 0.0f;
                        cb_ex[idx] = 0.0f;
                    }
                    continue;
                }
                double wsum = 0.0, ep_sum = 0.0, sg_sum = 0.0;
                for (int dk = -1; dk <= 0; dk++) {
                    for (int dj = -1; dj <= 0; dj++) {
                        double w = dz[k + dk] * dy[j + dj];
                        size_t cidx = CELL_IDX(k + dk, j + dj, i);
                        wsum += w;
                        ep_sum += w * (double)cell_eps_r[cidx];
                        sg_sum += w * (double)cell_sigma[cidx];
                    }
                }
                double eps = EPS0 * (ep_sum / wsum);
                double sig_diel = sg_sum / wsum;
                if (in_box && sig_diel > 1e-9) {
                    PUSH_LOSS_EDGE(idx, 0, sig_diel * dvol);
                }
                double sig = sig_diel;
                if (is_port) {
                    sig += l_port_x / (r_src_ohm * w_dual_y * dzh[k]);
                }
                double a = eps / dt + 0.5 * sig;
                double b = eps / dt - 0.5 * sig;
                ca_ex[idx] = (float)(b / a);
                cb_ex[idx] = (float)(1.0 / a);
            }
        }
    }

    for (int k = 1; k < nz; k++) {
        for (int j = 0; j < ny; j++) {
            for (int i = 1; i < nx; i++) {
                size_t idx = EY_IDX(k, j, i);
                int in_box = (i >= npml && i <= nx - npml &&
                              j >= npml && j < ny - npml &&
                              k >= npml && k <= nz - npml);
                double dvol = dxh[i] * dy[j] * dzh[k];
                if (pec_ey[idx]) {
                    if (r_sheet_ohm > 1e-9) {
                        double wsum = 0.0, ep_sum = 0.0;
                        for (int dk = -1; dk <= 0; dk++) {
                            for (int di = -1; di <= 0; di++) {
                                double w = dz[k + dk] * dx[i + di];
                                wsum += w;
                                ep_sum += w * (double)cell_eps_r[CELL_IDX(k + dk, j, i + di)];
                            }
                        }
                        double eps = EPS0 * (ep_sum / wsum);
                        double sig_sheet = 1.0 / (r_sheet_ohm * dzh[k]);
                        double expo = exp(-sig_sheet * dt / eps);
                        ca_ey[idx] = (float)expo;
                        cb_ey[idx] = (float)((1.0 - expo) / sig_sheet);
                        if (in_box) PUSH_LOSS_EDGE(idx, 1, sig_sheet * dvol);
                    } else {
                        ca_ey[idx] = 0.0f;
                        cb_ey[idx] = 0.0f;
                    }
                    continue;
                }
                double wsum = 0.0, ep_sum = 0.0, sg_sum = 0.0;
                for (int dk = -1; dk <= 0; dk++) {
                    for (int di = -1; di <= 0; di++) {
                        double w = dz[k + dk] * dx[i + di];
                        size_t cidx = CELL_IDX(k + dk, j, i + di);
                        wsum += w;
                        ep_sum += w * (double)cell_eps_r[cidx];
                        sg_sum += w * (double)cell_sigma[cidx];
                    }
                }
                double eps = EPS0 * (ep_sum / wsum);
                double sig_diel = sg_sum / wsum;
                if (in_box && sig_diel > 1e-9) {
                    PUSH_LOSS_EDGE(idx, 1, sig_diel * dvol);
                }
                double a = eps / dt + 0.5 * sig_diel;
                double b = eps / dt - 0.5 * sig_diel;
                ca_ey[idx] = (float)(b / a);
                cb_ey[idx] = (float)(1.0 / a);
            }
        }
    }

    for (int k = 0; k < nz; k++) {
        for (int j = 1; j < ny; j++) {
            for (int i = 1; i < nx; i++) {
                size_t idx = EZ_IDX(k, j, i);
                int in_box = (i >= npml && i <= nx - npml &&
                              j >= npml && j <= ny - npml &&
                              k >= npml && k < nz - npml);
                int is_port = (port_axis == 2 && i == p_i && j >= p_j0 && j < p_j1 && k >= p_k0 && k < p_k1);
                double dvol = dxh[i] * dyh[j] * dz[k];
                if (pec_ez[idx] && !is_port) {
                    ca_ez[idx] = 0.0f;
                    cb_ez[idx] = 0.0f;
                    continue;
                }
                double wsum = 0.0, ep_sum = 0.0, sg_sum = 0.0;
                for (int dj = -1; dj <= 0; dj++) {
                    for (int di = -1; di <= 0; di++) {
                        double w = dy[j + dj] * dx[i + di];
                        size_t cidx = CELL_IDX(k, j + dj, i + di);
                        wsum += w;
                        ep_sum += w * (double)cell_eps_r[cidx];
                        sg_sum += w * (double)cell_sigma[cidx];
                    }
                }
                double eps = EPS0 * (ep_sum / wsum);
                double sig_diel = sg_sum / wsum;
                if (in_box && sig_diel > 1e-9) {
                    PUSH_LOSS_EDGE(idx, 2, sig_diel * dvol);
                }
                double sig = sig_diel;
                if (is_port) {
                    sig += h_port_z / (r_src_ohm * dxh[i] * w_dual_y);
                }
                double a = eps / dt + 0.5 * sig;
                double b = eps / dt - 0.5 * sig;
                ca_ez[idx] = (float)(b / a);
                cb_ez[idx] = (float)(1.0 / a);
            }
        }
    }

    /* 8-cell CPML profiles */
    const double m_ord = 3.0;
    const double kappa_max = 7.0;
    const double alpha_max = 0.04;
    const double eta0 = sqrt(MU0 / EPS0);

    float *kx_e = (float *)malloc((size_t)(nx + 1) * sizeof(float));
    float *bx_e = (float *)calloc((size_t)(nx + 1), sizeof(float));
    float *cx_e = (float *)calloc((size_t)(nx + 1), sizeof(float));
    float *kx_h = (float *)malloc((size_t)nx * sizeof(float));
    float *bx_h = (float *)calloc((size_t)nx, sizeof(float));
    float *cx_h = (float *)calloc((size_t)nx, sizeof(float));

    float *ky_e = (float *)malloc((size_t)(ny + 1) * sizeof(float));
    float *by_e = (float *)calloc((size_t)(ny + 1), sizeof(float));
    float *cy_e = (float *)calloc((size_t)(ny + 1), sizeof(float));
    float *ky_h = (float *)malloc((size_t)ny * sizeof(float));
    float *by_h = (float *)calloc((size_t)ny, sizeof(float));
    float *cy_h = (float *)calloc((size_t)ny, sizeof(float));

    float *kz_e = (float *)malloc((size_t)(nz + 1) * sizeof(float));
    float *bz_e = (float *)calloc((size_t)(nz + 1), sizeof(float));
    float *cz_e = (float *)calloc((size_t)(nz + 1), sizeof(float));
    float *kz_h = (float *)malloc((size_t)nz * sizeof(float));
    float *bz_h = (float *)calloc((size_t)nz, sizeof(float));
    float *cz_h = (float *)calloc((size_t)nz, sizeof(float));

    for (int i = 0; i <= nx; i++) kx_e[i] = 1.0f;
    for (int i = 0; i < nx; i++)  kx_h[i] = 1.0f;
    for (int j = 0; j <= ny; j++) ky_e[j] = 1.0f;
    for (int j = 0; j < ny; j++)  ky_h[j] = 1.0f;
    for (int k = 0; k <= nz; k++) kz_e[k] = 1.0f;
    for (int k = 0; k < nz; k++)  kz_h[k] = 1.0f;

    #define SET_PML_COEFF(rho, d_pml, k_arr, b_arr, c_arr, idx) do { \
        double r_clip = (rho) > 0.0 ? ((rho) > 1.0 ? 1.0 : (rho)) : 0.0; \
        if (r_clip > 0.0) { \
            double s_max = 0.8 * (m_ord + 1.0) / (eta0 * (d_pml) / (double)npml); \
            double sig_u = s_max * pow(r_clip, m_ord); \
            double kap_u = 1.0 + (kappa_max - 1.0) * pow(r_clip, m_ord); \
            double alp_u = alpha_max * (1.0 - r_clip); \
            double b_val = exp(-(sig_u / kap_u + alp_u) * (dt / EPS0)); \
            double c_val = sig_u * (b_val - 1.0) / (sig_u * kap_u + kap_u * kap_u * alp_u + 1e-30); \
            (k_arr)[idx] = (float)kap_u; \
            (b_arr)[idx] = (float)b_val; \
            (c_arr)[idx] = (float)c_val; \
        } \
    } while (0)

    double lx_lo = x[npml] - x[0], lx_hi = x[nx] - x[nx - npml];
    for (int i = 1; i < npml; i++) {
        SET_PML_COEFF((x[npml] - x[i]) / lx_lo, lx_lo, kx_e, bx_e, cx_e, i);
        SET_PML_COEFF((x[nx - i] - x[nx - npml]) / lx_hi, lx_hi, kx_e, bx_e, cx_e, nx - i);
    }
    for (int i = 0; i < npml; i++) {
        double xc_lo = 0.5 * (x[i] + x[i + 1]);
        double xc_hi = 0.5 * (x[nx - 1 - i] + x[nx - i]);
        SET_PML_COEFF((x[npml] - xc_lo) / lx_lo, lx_lo, kx_h, bx_h, cx_h, i);
        SET_PML_COEFF((xc_hi - x[nx - npml]) / lx_hi, lx_hi, kx_h, bx_h, cx_h, nx - 1 - i);
    }

    double ly_lo = y[npml] - y[0], ly_hi = y[ny] - y[ny - npml];
    for (int j = 1; j < npml; j++) {
        SET_PML_COEFF((y[npml] - y[j]) / ly_lo, ly_lo, ky_e, by_e, cy_e, j);
        SET_PML_COEFF((y[ny - j] - y[ny - npml]) / ly_hi, ly_hi, ky_e, by_e, cy_e, ny - j);
    }
    for (int j = 0; j < npml; j++) {
        double yc_lo = 0.5 * (y[j] + y[j + 1]);
        double yc_hi = 0.5 * (y[ny - 1 - j] + y[ny - j]);
        SET_PML_COEFF((y[npml] - yc_lo) / ly_lo, ly_lo, ky_h, by_h, cy_h, j);
        SET_PML_COEFF((yc_hi - y[ny - npml]) / ly_hi, ly_hi, ky_h, by_h, cy_h, ny - 1 - j);
    }

    double lz_lo = z[npml] - z[0], lz_hi = z[nz] - z[nz - npml];
    for (int k = 1; k < npml; k++) {
        SET_PML_COEFF((z[npml] - z[k]) / lz_lo, lz_lo, kz_e, bz_e, cz_e, k);
        SET_PML_COEFF((z[nz - k] - z[nz - npml]) / lz_hi, lz_hi, kz_e, bz_e, cz_e, nz - k);
    }
    for (int k = 0; k < npml; k++) {
        double zc_lo = 0.5 * (z[k] + z[k + 1]);
        double zc_hi = 0.5 * (z[nz - 1 - k] + z[nz - k]);
        SET_PML_COEFF((z[npml] - zc_lo) / lz_lo, lz_lo, kz_h, bz_h, cz_h, k);
        SET_PML_COEFF((zc_hi - z[nz - npml]) / lz_hi, lz_hi, kz_h, bz_h, cz_h, nz - 1 - k);
    }

    float *psi_Ex_y = (float *)calloc(n_ex, sizeof(float));
    float *psi_Ex_z = (float *)calloc(n_ex, sizeof(float));
    float *psi_Ey_z = (float *)calloc(n_ey, sizeof(float));
    float *psi_Ey_x = (float *)calloc(n_ey, sizeof(float));
    float *psi_Ez_x = (float *)calloc(n_ez, sizeof(float));
    float *psi_Ez_y = (float *)calloc(n_ez, sizeof(float));

    float *psi_Hx_y = (float *)calloc(n_hx, sizeof(float));
    float *psi_Hx_z = (float *)calloc(n_hx, sizeof(float));
    float *psi_Hy_z = (float *)calloc(n_hy, sizeof(float));
    float *psi_Hy_x = (float *)calloc(n_hy, sizeof(float));
    float *psi_Hz_x = (float *)calloc(n_hz, sizeof(float));
    float *psi_Hz_y = (float *)calloc(n_hz, sizeof(float));

    float *inv_dx  = (float *)malloc((size_t)nx * sizeof(float));
    float *inv_dy  = (float *)malloc((size_t)ny * sizeof(float));
    float *inv_dz  = (float *)malloc((size_t)nz * sizeof(float));
    float *inv_dxh = (float *)malloc((size_t)(nx + 1) * sizeof(float));
    float *inv_dyh = (float *)malloc((size_t)(ny + 1) * sizeof(float));
    float *inv_dzh = (float *)malloc((size_t)(nz + 1) * sizeof(float));

    for (int i = 0; i < nx; i++)  inv_dx[i] = (float)(1.0 / dx[i]);
    for (int j = 0; j < ny; j++)  inv_dy[j] = (float)(1.0 / dy[j]);
    for (int k = 0; k < nz; k++)  inv_dz[k] = (float)(1.0 / dz[k]);
    for (int i = 0; i <= nx; i++) inv_dxh[i] = (float)(1.0 / dxh[i]);
    for (int j = 0; j <= ny; j++) inv_dyh[j] = (float)(1.0 / dyh[j]);
    for (int k = 0; k <= nz; k++) inv_dzh[k] = (float)(1.0 / dzh[k]);

    /* Anchor frequencies for volumetric dielectric + ENIG conductor loss DFT */
    int anc_idx[MAX_LOSS_ANCHORS];
    int n_anc = 0;
    if (n_freqs <= MAX_LOSS_ANCHORS) {
        for (int f = 0; f < n_freqs; f++) anc_idx[n_anc++] = f;
    } else {
        const double key_f[] = {
            730.0e6, 760.0e6, 775.5e6, 792.0e6, 815.0e6, 832.5e6,
            847.0e6, 857.0e6, 863.0e6, 863.1e6, 866.5e6, 868.3e6,
            869.5e6, 870.0e6, 876.5e6, 890.0e6, 915.0e6, 940.0e6,
            1733.0e6, 2599.5e6
        };
        uint8_t *used = (uint8_t *)calloc((size_t)n_freqs, 1);
        for (size_t m = 0; m < sizeof(key_f) / sizeof(key_f[0]); m++) {
            int best = 0;
            double best_d = 1e30;
            for (int f = 0; f < n_freqs; f++) {
                double d = fabs(freqs_hz[f] - key_f[m]);
                if (d < best_d) { best_d = d; best = f; }
            }
            if (!used[best] && n_anc < MAX_LOSS_ANCHORS) {
                used[best] = 1;
                anc_idx[n_anc++] = best;
            }
        }
        int rem = MAX_LOSS_ANCHORS - n_anc;
        for (int r = 0; r < rem; r++) {
            int f = (int)llround((double)r * (double)(n_freqs - 1) / (double)(rem > 1 ? rem - 1 : 1));
            while (f < n_freqs && used[f]) f++;
            if (f >= n_freqs) {
                f = n_freqs - 1;
                while (f >= 0 && used[f]) f--;
            }
            if (f >= 0 && !used[f]) {
                used[f] = 1;
                anc_idx[n_anc++] = f;
            }
        }
        free(used);
        for (int a = 0; a < n_anc - 1; a++) {
            for (int b = a + 1; b < n_anc; b++) {
                if (anc_idx[b] < anc_idx[a]) {
                    int tmp = anc_idx[a]; anc_idx[a] = anc_idx[b]; anc_idx[b] = tmp;
                }
            }
        }
    }

    const size_t loss_stride = 2U * n_loss;
    float *loss_dft = (n_loss > 0) ? (float *)calloc((size_t)n_anc * loss_stride, sizeof(float)) : NULL;
    float *loss_sample = (n_loss > 0) ? (float *)malloc(n_loss * sizeof(float)) : NULL;
    if (n_loss > 0 && (!loss_dft || !loss_sample)) {
        return -3;
    }

    const float dt_mu0 = (float)(dt / MU0);
    const double tau = 1.0 / (PI * f_span_pulse);
    const double t0 = 4.2 * tau;
    const int taper_start = (int)(0.88 * (double)n_steps);

    double *v_trace = (double *)calloc((size_t)n_steps, sizeof(double));
    double *i_trace = (double *)calloc((size_t)n_steps, sizeof(double));

    double v_port_prev = 0.0;

    for (int step = 0; step < n_steps; step++) {
        /* 1. Update H fields (n - 1/2 -> n + 1/2) */
        #pragma omp parallel for schedule(static)
        for (int k = 0; k < nz; k++) {
            const float idz = inv_dz[k];
            const float kzh = kz_h[k], bzh = bz_h[k], czh = cz_h[k];
            const int pml_z = (k < npml || k >= nz - npml);
            for (int j = 0; j < ny; j++) {
                const float idy = inv_dy[j];
                const float kyh = ky_h[j], byh = by_h[j], cyh = cy_h[j];
                const int pml_y = (j < npml || j >= ny - npml);
                for (int i = 0; i <= nx; i++) {
                    size_t idx = HX_IDX(k, j, i);
                    float dEz_dy = (Ez[EZ_IDX(k, j + 1, i)] - Ez[EZ_IDX(k, j, i)]) * idy;
                    float dEy_dz = (Ey[EY_IDX(k + 1, j, i)] - Ey[EY_IDX(k, j, i)]) * idz;
                    float curl_x = dEz_dy / kyh - dEy_dz / kzh;
                    if (pml_y) {
                        psi_Hx_y[idx] = byh * psi_Hx_y[idx] + cyh * dEz_dy;
                        curl_x += psi_Hx_y[idx];
                    }
                    if (pml_z) {
                        psi_Hx_z[idx] = bzh * psi_Hx_z[idx] + czh * dEy_dz;
                        curl_x -= psi_Hx_z[idx];
                    }
                    Hx[idx] -= dt_mu0 * curl_x;
                }
            }
        }

        #pragma omp parallel for schedule(static)
        for (int k = 0; k < nz; k++) {
            const float idz = inv_dz[k];
            const float kzh = kz_h[k], bzh = bz_h[k], czh = cz_h[k];
            const int pml_z = (k < npml || k >= nz - npml);
            for (int j = 0; j <= ny; j++) {
                for (int i = 0; i < nx; i++) {
                    const float idx_f = inv_dx[i];
                    const float kxh = kx_h[i], bxh = bx_h[i], cxh = cx_h[i];
                    const int pml_x = (i < npml || i >= nx - npml);
                    size_t idx = HY_IDX(k, j, i);
                    float dEx_dz = (Ex[EX_IDX(k + 1, j, i)] - Ex[EX_IDX(k, j, i)]) * idz;
                    float dEz_dx = (Ez[EZ_IDX(k, j, i + 1)] - Ez[EZ_IDX(k, j, i)]) * idx_f;
                    float curl_y = dEx_dz / kzh - dEz_dx / kxh;
                    if (pml_z) {
                        psi_Hy_z[idx] = bzh * psi_Hy_z[idx] + czh * dEx_dz;
                        curl_y += psi_Hy_z[idx];
                    }
                    if (pml_x) {
                        psi_Hy_x[idx] = bxh * psi_Hy_x[idx] + cxh * dEz_dx;
                        curl_y -= psi_Hy_x[idx];
                    }
                    Hy[idx] -= dt_mu0 * curl_y;
                }
            }
        }

        #pragma omp parallel for schedule(static)
        for (int k = 0; k <= nz; k++) {
            for (int j = 0; j < ny; j++) {
                const float idy = inv_dy[j];
                const float kyh = ky_h[j], byh = by_h[j], cyh = cy_h[j];
                const int pml_y = (j < npml || j >= ny - npml);
                for (int i = 0; i < nx; i++) {
                    const float idx_f = inv_dx[i];
                    const float kxh = kx_h[i], bxh = bx_h[i], cxh = cx_h[i];
                    const int pml_x = (i < npml || i >= nx - npml);
                    size_t idx = HZ_IDX(k, j, i);
                    float dEy_dx = (Ey[EY_IDX(k, j, i + 1)] - Ey[EY_IDX(k, j, i)]) * idx_f;
                    float dEx_dy = (Ex[EX_IDX(k, j + 1, i)] - Ex[EX_IDX(k, j, i)]) * idy;
                    float curl_z = dEy_dx / kxh - dEx_dy / kyh;
                    if (pml_x) {
                        psi_Hz_x[idx] = bxh * psi_Hz_x[idx] + cxh * dEy_dx;
                        curl_z += psi_Hz_x[idx];
                    }
                    if (pml_y) {
                        psi_Hz_y[idx] = byh * psi_Hz_y[idx] + cyh * dEx_dy;
                        curl_z -= psi_Hz_y[idx];
                    }
                    Hz[idx] -= dt_mu0 * curl_z;
                }
            }
        }

        /* 2. Update E fields (n -> n + 1) */
        const double t_half = ((double)step + 0.5) * dt;
        const double arg = (t_half - t0) / tau;
        const double v_src = exp(-arg * arg) * cos(2.0 * PI * f0_pulse * (t_half - t0));
        const float j_src_ex = (port_axis == 0) ? (float)(v_src / (r_src_ohm * w_dual_y * dzh[p_k0])) : 0.0f;
        const float j_src_ez = (port_axis == 2) ? (float)(v_src / (r_src_ohm * dxh[p_i] * w_dual_y)) : 0.0f;

        #pragma omp parallel for schedule(static)
        for (int k = 1; k < nz; k++) {
            const float idzh = inv_dzh[k];
            const float kze = kz_e[k], bze = bz_e[k], cze = cz_e[k];
            const int pml_z = (k < npml || k > nz - npml);
            for (int j = 1; j < ny; j++) {
                const float idyh = inv_dyh[j];
                const float kye = ky_e[j], bye = by_e[j], cye = cy_e[j];
                const int pml_y = (j < npml || j > ny - npml);
                for (int i = 0; i < nx; i++) {
                    size_t idx = EX_IDX(k, j, i);
                    float cb = cb_ex[idx];
                    if (cb == 0.0f) continue;
                    float dHz_dy = (Hz[HZ_IDX(k, j, i)] - Hz[HZ_IDX(k, j - 1, i)]) * idyh;
                    float dHy_dz = (Hy[HY_IDX(k, j, i)] - Hy[HY_IDX(k - 1, j, i)]) * idzh;
                    float curl_x = dHz_dy / kye - dHy_dz / kze;
                    if (pml_y) {
                        psi_Ex_y[idx] = bye * psi_Ex_y[idx] + cye * dHz_dy;
                        curl_x += psi_Ex_y[idx];
                    }
                    if (pml_z) {
                        psi_Ex_z[idx] = bze * psi_Ex_z[idx] + cze * dHy_dz;
                        curl_x -= psi_Ex_z[idx];
                    }
                    if (port_axis == 0 && i == p_i && j >= p_j0 && j < p_j1 && k == p_k0) {
                        curl_x -= j_src_ex;
                    }
                    Ex[idx] = ca_ex[idx] * Ex[idx] + cb * curl_x;
                }
            }
        }

        #pragma omp parallel for schedule(static)
        for (int k = 1; k < nz; k++) {
            const float idzh = inv_dzh[k];
            const float kze = kz_e[k], bze = bz_e[k], cze = cz_e[k];
            const int pml_z = (k < npml || k > nz - npml);
            for (int j = 0; j < ny; j++) {
                for (int i = 1; i < nx; i++) {
                    const float idxh = inv_dxh[i];
                    const float kxe = kx_e[i], bxe = bx_e[i], cxe = cx_e[i];
                    const int pml_x = (i < npml || i > nx - npml);
                    size_t idx = EY_IDX(k, j, i);
                    float cb = cb_ey[idx];
                    if (cb == 0.0f) continue;
                    float dHx_dz = (Hx[HX_IDX(k, j, i)] - Hx[HX_IDX(k - 1, j, i)]) * idzh;
                    float dHz_dx = (Hz[HZ_IDX(k, j, i)] - Hz[HZ_IDX(k, j, i - 1)]) * idxh;
                    float curl_y = dHx_dz / kze - dHz_dx / kxe;
                    if (pml_z) {
                        psi_Ey_z[idx] = bze * psi_Ey_z[idx] + cze * dHx_dz;
                        curl_y += psi_Ey_z[idx];
                    }
                    if (pml_x) {
                        psi_Ey_x[idx] = bxe * psi_Ey_x[idx] + cxe * dHz_dx;
                        curl_y -= psi_Ey_x[idx];
                    }
                    Ey[idx] = ca_ey[idx] * Ey[idx] + cb * curl_y;
                }
            }
        }

        #pragma omp parallel for schedule(static)
        for (int k = 0; k < nz; k++) {
            for (int j = 1; j < ny; j++) {
                const float idyh = inv_dyh[j];
                const float kye = ky_e[j], bye = by_e[j], cye = cy_e[j];
                const int pml_y = (j < npml || j > ny - npml);
                for (int i = 1; i < nx; i++) {
                    const float idxh = inv_dxh[i];
                    const float kxe = kx_e[i], bxe = bx_e[i], cxe = cx_e[i];
                    const int pml_x = (i < npml || i > nx - npml);
                    size_t idx = EZ_IDX(k, j, i);
                    float cb = cb_ez[idx];
                    if (cb == 0.0f) continue;
                    float dHy_dx = (Hy[HY_IDX(k, j, i)] - Hy[HY_IDX(k, j, i - 1)]) * idxh;
                    float dHx_dy = (Hx[HX_IDX(k, j, i)] - Hx[HX_IDX(k, j - 1, i)]) * idyh;
                    float curl_z = dHy_dx / kxe - dHx_dy / kye;
                    if (pml_x) {
                        psi_Ez_x[idx] = bxe * psi_Ez_x[idx] + cxe * dHy_dx;
                        curl_z += psi_Ez_x[idx];
                    }
                    if (pml_y) {
                        psi_Ez_y[idx] = bye * psi_Ez_y[idx] + cye * dHx_dy;
                        curl_z -= psi_Ez_y[idx];
                    }
                    if (port_axis == 2 && i == p_i && j >= p_j0 && j < p_j1 && k >= p_k0 && k < p_k1) {
                        curl_z -= j_src_ez;
                    }
                    Ez[idx] = ca_ez[idx] * Ez[idx] + cb * curl_z;
                }
            }
        }

        /* Sample port voltage V(n + 1) and exact half-step Thevenin port V/I at (n + 0.5)*dt */
        double v_prev = (step > 0) ? v_port_prev : 0.0;
        double v_now = 0.0;
        if (port_axis == 0) {
            for (int j = p_j0; j < p_j1; j++) {
                v_now += (-(double)Ex[EX_IDX(p_k0, j, p_i)] * dx[p_i]) * (dyh[j] / w_dual_y);
            }
        } else {
            for (int k = p_k0; k < p_k1; k++) {
                double ez_avg = 0.0;
                for (int j = p_j0; j < p_j1; j++) {
                    ez_avg += (double)Ez[EZ_IDX(k, j, p_i)] * (dyh[j] / w_dual_y);
                }
                v_now -= ez_avg * dz[k];
            }
        }
        v_port_prev = v_now;
        double v_half = 0.5 * (v_prev + v_now);
        v_trace[step] = v_half;
        i_trace[step] = (v_src - v_half) / r_src_ohm;

        /* Accumulate E-field DFT phasors on all lossy dielectric + ENIG edges
         * every LOSS_DECIM steps (Nyquist > 45 GHz >> 2.65 GHz). */
        if (n_loss > 0 && (step % LOSS_DECIM) == 0) {
            const float *e_arrs[3] = { Ex, Ey, Ez };
            #pragma omp parallel for schedule(static)
            for (size_t m = 0; m < n_loss; m++) {
                loss_sample[m] = e_arrs[loss_edges[m].axis][loss_edges[m].idx];
            }

            double win = 1.0;
            if (step >= taper_start) {
                double u = (double)(step - taper_start) / (double)(n_steps - taper_start);
                win = 0.5 * (1.0 + cos(PI * u));
            }
            const double w_dt = win * ((double)LOSS_DECIM * dt);
            const double t_e = ((double)step + 1.0) * dt;

            #pragma omp parallel for schedule(static)
            for (int a = 0; a < n_anc; a++) {
                const double omega = 2.0 * PI * freqs_hz[anc_idx[a]];
                const float ce = (float)(w_dt * cos(omega * t_e));
                const float se = (float)(-w_dt * sin(omega * t_e));
                float *acc = loss_dft + (size_t)a * loss_stride;
                for (size_t m = 0; m < n_loss; m++) {
                    const float ev = loss_sample[m];
                    acc[2U * m + 0U] += ev * ce;
                    acc[2U * m + 1U] += ev * se;
                }
            }
        }
    }

    /* Port DFT at all requested frequencies */
    for (int f_idx = 0; f_idx < n_freqs; f_idx++) {
        const double omega = 2.0 * PI * freqs_hz[f_idx];
        double vr = 0.0, vi = 0.0, ir = 0.0, ii = 0.0;
        for (int step = 0; step < n_steps; step++) {
            double win = 1.0;
            if (step >= taper_start) {
                double u = (double)(step - taper_start) / (double)(n_steps - taper_start);
                win = 0.5 * (1.0 + cos(PI * u));
            }
            double th = ((double)step + 0.5) * dt;
            double c = cos(omega * th), s = sin(omega * th);
            vr += win * v_trace[step] * c * dt;
            vi -= win * v_trace[step] * s * dt;
            ir += win * i_trace[step] * c * dt;
            ii -= win * i_trace[step] * s * dt;
        }
        out_v_re[f_idx] = vr;
        out_v_im[f_idx] = vi;
        out_i_re[f_idx] = ir;
        out_i_im[f_idx] = ii;
    }

    /* Evaluate frequency-resolved P_loss(f) = P_diel(f) + P_ENIG(f) and
     * eta_rad(f) = (P_acc(f) - P_loss(f)) / P_acc(f) at each anchor frequency,
     * then interpolate across the dense frequency vector. */
    double anc_eta[MAX_LOSS_ANCHORS];
    for (int a = 0; a < n_anc; a++) {
        const int f_idx = anc_idx[a];
        double p_loss = 0.0;
        if (n_loss > 0) {
            const float *acc = loss_dft + (size_t)a * loss_stride;
            #pragma omp parallel for reduction(+:p_loss) schedule(static)
            for (size_t m = 0; m < n_loss; m++) {
                const double er_v = acc[2U * m + 0U];
                const double ei_v = acc[2U * m + 1U];
                p_loss += 0.5 * (double)loss_edges[m].g_vol * (er_v * er_v + ei_v * ei_v);
            }
        }
        const double p_acc = 0.5 * (out_v_re[f_idx] * out_i_re[f_idx] +
                                    out_v_im[f_idx] * out_i_im[f_idx]);
        double eta = 0.65;
        if (p_acc > 1e-35) {
            eta = (p_acc - p_loss) / p_acc;
        }
        if (eta < 0.01) eta = 0.01;
        if (eta > 0.995) eta = 0.995;
        anc_eta[a] = eta;
    }

    for (int f_idx = 0; f_idx < n_freqs; f_idx++) {
        const double f = freqs_hz[f_idx];
        if (f <= freqs_hz[anc_idx[0]] || n_anc == 1) {
            out_rad_eff[f_idx] = anc_eta[0];
        } else if (f >= freqs_hz[anc_idx[n_anc - 1]]) {
            out_rad_eff[f_idx] = anc_eta[n_anc - 1];
        } else {
            int hi = 1;
            while (hi < n_anc - 1 && freqs_hz[anc_idx[hi]] < f) hi++;
            int lo = hi - 1;
            double f_lo = freqs_hz[anc_idx[lo]];
            double f_hi = freqs_hz[anc_idx[hi]];
            double t = (f_hi > f_lo) ? ((f - f_lo) / (f_hi - f_lo)) : 0.0;
            out_rad_eff[f_idx] = (1.0 - t) * anc_eta[lo] + t * anc_eta[hi];
        }
    }

    free(dx); free(dy); free(dz);
    free(dxh); free(dyh); free(dzh);
    free(Ex); free(Ey); free(Ez);
    free(Hx); free(Hy); free(Hz);
    free(ca_ex); free(cb_ex); free(ca_ey); free(cb_ey); free(ca_ez); free(cb_ez);
    free(kx_e); free(bx_e); free(cx_e); free(kx_h); free(bx_h); free(cx_h);
    free(ky_e); free(by_e); free(cy_e); free(ky_h); free(by_h); free(cy_h);
    free(kz_e); free(bz_e); free(cz_e); free(kz_h); free(bz_h); free(cz_h);
    free(psi_Ex_y); free(psi_Ex_z); free(psi_Ey_z); free(psi_Ey_x); free(psi_Ez_x); free(psi_Ez_y);
    free(psi_Hx_y); free(psi_Hx_z); free(psi_Hy_z); free(psi_Hy_x); free(psi_Hz_x); free(psi_Hz_y);
    free(inv_dx); free(inv_dy); free(inv_dz);
    free(inv_dxh); free(inv_dyh); free(inv_dzh);
    free(loss_edges); free(loss_dft); free(loss_sample);
    free(v_trace); free(i_trace);

    return 0;
}
