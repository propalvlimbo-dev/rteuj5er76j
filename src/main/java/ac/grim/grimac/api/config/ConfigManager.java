package ac.grim.grimac.api.config;

/**
 * EFC-совместимость: Grim ConfigManager.
 * Возвращает значения Grim по умолчанию; наказаниями управляет конфиг EFC.
 */
public class ConfigManager {

    public int getIntElse(String path, int def) {
        return def;
    }

    public long getLongElse(String path, long def) {
        return def;
    }

    public double getDoubleElse(String path, double def) {
        return def;
    }

    public boolean getBooleanElse(String path, boolean def) {
        return def;
    }

    public String getStringElse(String path, String def) {
        return def;
    }
}
