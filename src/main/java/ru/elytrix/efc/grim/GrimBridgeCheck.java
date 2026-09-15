package ru.elytrix.efc.grim;

import java.util.UUID;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * EFC-обёртка Grim-проверки: ID, конфиг, наказания EFC.
 * Сама логика — дословный код Grim, вызывается через GrimBridge.
 */
public final class GrimBridgeCheck extends Check {

    public GrimBridgeCheck(ElytrixFuckCheats plugin, String name, String type, Category category) {
        super(plugin, name, type, category);
    }

    @Override
    public void onQuit(UUID uuid) {
        GrimBridge.onQuit(uuid);
    }
}
