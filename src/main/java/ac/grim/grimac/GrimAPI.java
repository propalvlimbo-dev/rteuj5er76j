package ac.grim.grimac;

/**
 * EFC-совместимость: Grim GrimAPI (только счётчик тиков).
 */
public class GrimAPI {

    public static final GrimAPI INSTANCE = new GrimAPI();

    private final TickManager tickManager = new TickManager();

    public TickManager getTickManager() {
        return tickManager;
    }

    public static final class TickManager {
        public int currentTick;
    }
}
