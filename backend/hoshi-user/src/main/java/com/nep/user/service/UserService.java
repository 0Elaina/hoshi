package com.nep.user.service;

import com.nep.user.vo.UserVO;

public interface UserService {
    /**
     * 创建用户
     * 
     * @param username 用户名
     * @param password 密码
     * @param nickname 昵称
     * @return 创建后的用户
     */
    UserVO createUser(String username, String password, String nickname);
}
