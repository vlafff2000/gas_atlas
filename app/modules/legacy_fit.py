"""Numerical fit copied verbatim from the supplied GDIAnalyzer.fit_trend_line.
See docs/MIGRATION.md for provenance and adapter validation.
"""
import numpy as np

class LegacyFit:
    def fit_trend_line(self, q, dp2):
        """
        Аппроксимация данных уравнением DP^2 = a*Q + b*Q^2
        Использует прямую нелинейную регрессию с ограничениями a>0, b>0.
        """
        from scipy.optimize import curve_fit

        q = np.array(q, dtype=float).flatten()
        dp2 = np.array(dp2, dtype=float).flatten()

        if len(q) != len(dp2):
            min_len = min(len(q), len(dp2))
            q = q[:min_len]
            dp2 = dp2[:min_len]

        if len(q) < 2:
            return None, None, None

        try:
            mask = (q > 0) & (~np.isnan(q)) & (~np.isnan(dp2)) & (dp2 > 0)
            if sum(mask) < 2:
                return None, None, None

            q_clean = q[mask]
            dp2_clean = dp2[mask]

            # Функция для подгонки: ΔP² = a·Q + b·Q²
            def model(Q, a, b):
                return a * Q + b * Q ** 2

            # Начальные приближения через линеаризацию
            y_lin = dp2_clean / q_clean
            coeffs_init = np.polyfit(q_clean, y_lin, 1)
            b_init = max(coeffs_init[0], 1e-10)
            a_init = max(coeffs_init[1], 1e-10)

            # Если начальные коэффициенты отрицательные — используем запасные
            if a_init <= 0 or b_init <= 0:
                # Простая оценка: k = среднее(ΔP²/Q)
                k = np.mean(dp2_clean / q_clean)
                a_init = k * 0.5
                b_init = k * 0.5 / max(q_clean)

            try:
                # Прямая нелинейная регрессия с ограничениями
                bounds = ([1e-10, 1e-10], [np.inf, np.inf])
                popt, pcov = curve_fit(model, q_clean, dp2_clean,
                                       p0=[a_init, b_init],
                                       bounds=bounds,
                                       maxfev=5000)
                a, b = popt[0], popt[1]
            except:
                # Если не получилось — используем линеаризацию
                coeffs = np.polyfit(q_clean, y_lin, 1)
                b = max(coeffs[0], 1e-10)
                a = max(coeffs[1], 1e-10)

            # Гарантируем положительность
            a = max(a, 1e-10)
            b = max(b, 1e-10)

            # R²
            y_pred = a * q_clean + b * q_clean ** 2
            ss_res = np.sum((dp2_clean - y_pred) ** 2)
            ss_tot = np.sum((dp2_clean - np.mean(dp2_clean)) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

            return a, b, r2

        except Exception as e:
            print(f"    Ошибка при расчете коэффициентов: {e}")
            return None, None, None
