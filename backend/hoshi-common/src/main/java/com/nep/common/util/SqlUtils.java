package com.nep.common.util;

import org.springframework.util.StringUtils;

public final class SqlUtils {
    private SqlUtils() {
    }

    public static String escapeLike(String value) {
        if (!StringUtils.hasText(value))
            return "";
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
