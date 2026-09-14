package ru.elytrix.efc.check;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import ru.elytrix.efc.ElytrixFuckCheats;

/**
 * Реестр проверок. Конкретные проверки регистрируются здесь.
 * Билд №1: реестр пуст, проверки едут следующим коммитом.
 */
public final class CheckManager {

    private final ElytrixFuckCheats plugin;
    private final List<Check> checks = new ArrayList<>();

    public CheckManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
        registerAll();
    }

    private void registerAll() {
        // TODO билд №2: new KillAuraA(plugin), new ReachA(plugin), new AutoClickerA(plugin)
    }

    public void register(Check check) {
        checks.add(check);
    }

    public List<Check> getChecks() {
        return Collections.unmodifiableList(checks);
    }

    public Check get(String id) {
        for (Check check : checks) {
            if (check.id().equalsIgnoreCase(id)) {
                return check;
            }
        }
        return null;
    }
}
